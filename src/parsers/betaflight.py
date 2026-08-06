"""
Parser de logs Betaflight (blackbox, extension .BBL).

Diferencia clave respecto a ArduPilot/PX4: el formato binario de blackbox no
tiene una libreria Python de referencia mantenida (a diferencia de
pymavlink/pyulog, que son oficiales). La propia documentacion de Betaflight
recomienda usar `blackbox_decode`, la herramienta oficial en C/C++
(https://github.com/betaflight/blackbox-tools), para convertir el binario a
CSV, y trabajar sobre ese CSV. Este modulo sigue ese mismo camino en vez de
reimplementar el parser binario desde cero: se invoca `blackbox_decode` como
subproceso y se parsea el CSV resultante.

Limitacion importante que merece la pena documentar (y explicar en una
entrevista): las columnas del CSV de blackbox NO son estables entre
versiones de firmware ni segun los flags de decodificacion usados. Por eso
este parser busca varios alias posibles por campo en vez de asumir un
nombre de columna fijo, y deja en None lo que no encuentra en vez de fallar.

Otra limitacion de fondo: Betaflight es un firmware de vuelo acrobatico
("acro"/rate-based"). Por defecto el blackbox NO registra actitud absoluta
(roll/pitch/yaw), solo velocidades angulares del giroscopio y el setpoint
del piloto. Por eso este parser deja roll/pitch/yaw sin rellenar salvo que
el log incluya especificamente el modo de depuracion de angulo.
"""

import csv
import shutil
import subprocess
from pathlib import Path

from .base import FlightEvent, FlightLog, FlightRecord, Source

# Cada entrada es una lista de alias posibles para la misma magnitud, en
# orden de preferencia. blackbox_decode cambia el nombre exacto de columna
# segun si se le pide conversion de unidades (--unit-voltage, etc.) o no.
_COLUMN_ALIASES: dict[str, list[str]] = {
    "time_us": ["time (us)", "time"],
    "lat": ["GPS_coord[0]"],
    "lon": ["GPS_coord[1]"],
    "alt_m": ["GPS_altitude"],
    "gps_speed_cms": ["GPS_speed"],
    "vbat": ["vbatLatest (V)", "vbatLatest"],
    "amperage": ["amperageLatest (A)", "amperageLatest"],
    "rssi": ["rssi"],
    "failsafe_phase": ["failsafePhase"],
    "rx_signal_received": ["rxSignalReceived"],
}


def _find_column(header: list[str], field: str) -> str | None:
    """Busca en la cabecera del CSV la primera columna que coincida con algun alias de `field`."""
    for alias in _COLUMN_ALIASES[field]:
        if alias in header:
            return alias
    return None


def decode_bbl_to_csv(bbl_path: str, output_dir: str) -> str:
    """
    Convierte un log .BBL binario a CSV usando la herramienta oficial `blackbox_decode`.

    Requiere que `blackbox_decode` (parte de betaflight/blackbox-tools) este
    instalado y disponible en el PATH del sistema. Se lanza como subproceso
    en vez de re-implementar el formato binario porque es la herramienta que
    el propio proyecto Betaflight mantiene y valida contra cada nueva
    version de firmware.
    """
    if shutil.which("blackbox_decode") is None:
        raise RuntimeError(
            "No se encontro 'blackbox_decode' en el PATH. Instala "
            "betaflight/blackbox-tools (https://github.com/betaflight/blackbox-tools) "
            "para poder convertir logs .BBL a CSV antes de analizarlos."
        )

    output_path = Path(output_dir) / (Path(bbl_path).stem + ".csv")
    with open(output_path, "wb") as out_file:
        subprocess.run(["blackbox_decode", "--stdout", bbl_path], check=True, stdout=out_file)
    return str(output_path)


def parse_betaflight_csv(csv_path: str, source_bbl_path: str | None = None) -> FlightLog:
    """
    Lee un CSV ya decodificado por `blackbox_decode` y lo normaliza a FlightLog.

    Se separa de `decode_bbl_to_csv` a proposito: si alguien ya tiene el CSV
    (por ejemplo exportado desde el Blackbox Explorer grafico oficial), puede
    saltarse por completo la dependencia del binario `blackbox_decode`.
    """
    log = FlightLog(source=Source.BETAFLIGHT, source_file=source_bbl_path or csv_path)

    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        # DictReader.fieldnames a veces trae espacios extra segun la version
        # de blackbox_decode; normalizamos quitando espacios en los bordes.
        header = [h.strip() for h in (reader.fieldnames or [])]
        reader.fieldnames = header

        col = {field: _find_column(header, field) for field in _COLUMN_ALIASES}

        if col["time_us"] is None:
            raise ValueError(
                f"El CSV '{csv_path}' no tiene una columna de tiempo reconocible; "
                "puede que no sea un export valido de blackbox_decode."
            )

        t0_us: int | None = None
        prev_failsafe_phase: str | None = None
        prev_rx_signal: str | None = None

        for row in reader:
            raw_ts = row.get(col["time_us"])
            if raw_ts is None or raw_ts == "":
                continue
            ts_us = int(raw_ts)
            if t0_us is None:
                t0_us = ts_us
            ts = (ts_us - t0_us) / 1_000_000.0

            lat_raw = _row_float(row, col["lat"])
            lon_raw = _row_float(row, col["lon"])
            gps_speed_cms = _row_float(row, col["gps_speed_cms"])
            vbat = _row_float(row, col["vbat"])
            amperage = _row_float(row, col["amperage"])
            rssi = _row_float(row, col["rssi"])

            log.records.append(
                FlightRecord(
                    timestamp=ts,
                    # GPS_coord[0]/[1] en blackbox crudo viene en grados * 1e7,
                    # igual que en el binario nativo de PX4/ArduPilot.
                    lat=(lat_raw / 1e7) if lat_raw is not None else None,
                    lon=(lon_raw / 1e7) if lon_raw is not None else None,
                    alt=_row_float(row, col["alt_m"]),
                    groundspeed=(gps_speed_cms / 100.0) if gps_speed_cms is not None else None,
                    # Si la columna vino con sufijo "(V)"/"(A)" ya esta en
                    # voltios/amperios reales; si vino "cruda" (centivoltios/
                    # centiamperios) hay que dividir entre 100. Distinguimos
                    # mirando el nombre de columna que realmente se encontro.
                    battery_voltage=_scaled(vbat, col["vbat"]),
                    battery_current=_scaled(amperage, col["amperage"]),
                    rc_signal=rssi,
                )
            )

            # failsafePhase != 0 indica que el receptor entro en modo
            # failsafe (perdida de señal de radio). Solo generamos un evento
            # en la transicion, no en cada muestra, para no inundar el informe.
            failsafe_phase = row.get(col["failsafe_phase"]) if col["failsafe_phase"] else None
            if failsafe_phase is not None and failsafe_phase != prev_failsafe_phase:
                if failsafe_phase != "0":
                    log.events.append(
                        FlightEvent(
                            timestamp=ts,
                            category="rc_loss",
                            severity="critical",
                            description=f"Failsafe activado (fase {failsafe_phase})",
                        )
                    )
                prev_failsafe_phase = failsafe_phase

            rx_signal = row.get(col["rx_signal_received"]) if col["rx_signal_received"] else None
            if rx_signal is not None and rx_signal != prev_rx_signal:
                if rx_signal == "0":
                    log.events.append(
                        FlightEvent(
                            timestamp=ts,
                            category="rc_loss",
                            severity="warning",
                            description="Se dejo de recibir señal de radiocontrol valida",
                        )
                    )
                prev_rx_signal = rx_signal

    log.metadata["parsed_message_count"] = len(log.records) + len(log.events)
    return log


def _row_float(row: dict, colname: str | None) -> float | None:
    """Extrae y convierte a float una columna opcional de una fila del CSV."""
    if colname is None:
        return None
    value = row.get(colname)
    if value is None or value == "":
        return None
    return float(value)


def _scaled(value: float | None, colname: str | None) -> float | None:
    """
    Normaliza vbat/amperage a unidades reales (voltios/amperios).

    Si `blackbox_decode` ya convirtio la unidad (la columna incluye "(V)" o
    "(A)" en el nombre), el valor ya viene en unidades reales. Si no, viene
    en la unidad cruda de blackbox (centivoltios / centiamperios) y hay que
    dividir entre 100.
    """
    if value is None:
        return None
    if colname and ("(V)" in colname or "(A)" in colname):
        return value
    return value / 100.0
