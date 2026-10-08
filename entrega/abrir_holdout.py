# -*- coding: utf-8 -*-
"""
ABRIR EL AÑO CIEGO (protocolo V4) - UNA SOLA VEZ
================================================
Prueba en MT5 (data real de Axi) las estrategias CONGELADAS, en el año ciego, con el riesgo congelado,
y compara con el criterio que se escribio al congelar. El resultado decide sobre la version ENTERA.

  - Comprueba que los .mq5 congelados no se han tocado (huellas SHA-256).
  - Se niega a abrir un año ciego que ya se abrio (registro_holdout.json).
  - Marca el año ciego como abierto ANTES de probar: aunque se corte a medias, ya cuenta como abierto.
  - Si el resultado es SUSPENDIDO: no se quitan estrategias ni se repite. La version se rechaza.

Uso:  python abrir_holdout.py --manifiesto CONGELADO\\USTECH_V4_aaaammdd_hhmm\\manifest.json
      python abrir_holdout.py --manifiesto ... --solo-informe   (relee los informes de MT5 ya generados)
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import validador_sqx_mt5 as v          # noqa: E402

REGISTRO = HERE / "registro_holdout.json"


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def huella_codigo(path):
    """Huella de la operativa del .mq5 (la misma que usa el validador: sin numero magico ni fechas)."""
    return v.code_hash(path) if Path(path).exists() else None


def huellas_de(e):
    """Estrategias que ya se probaron en una apertura anterior: huellas de codigo y, solo para las que
    no tienen huella (falta el .mq5), sus nombres. SQX repite nombres entre vueltas, asi que el nombre
    solo se usa como ultimo recurso."""
    huellas, sin_huella = set(), set()
    for n, h in (e.get("huellas_codigo") or {}).items():
        huellas.add(h) if h else sin_huella.add(v.clean_name(n))
    if not e.get("huellas_codigo"):       # aperturas de antes de este cambio: se leen de su manifiesto
        try:
            mp = Path(e["manifest"])
            mp = mp if mp.is_absolute() else HERE / mp
            for s in json.loads(mp.read_text(encoding="utf-8")).get("seleccion", []):
                h = huella_codigo(mp.parent / s["mq5"])
                huellas.add(h) if h else sin_huella.add(v.clean_name(s["name"]))
        except Exception as ex:
            sys.exit(f"No puedo leer las estrategias que abrio {e.get('carpeta')} ({e.get('manifest')}): {ex}. "
                     "Sin eso no se puede saber si esta version repite alguna.")
    return {"huellas": huellas, "sin_huella": sin_huella}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifiesto", help="ruta del manifest.json congelado")
    ap.add_argument("--ultimo", help="carpeta (p.ej. USTECH_V4): usa su ultimo congelado pendiente de abrir")
    ap.add_argument("--solo-informe", action="store_true")
    a = ap.parse_args()
    if not a.manifiesto and a.ultimo:
        reg0 = json.loads(REGISTRO.read_text(encoding="utf-8")) if REGISTRO.exists() else []
        pend = [e for e in reg0 if e.get("carpeta") == a.ultimo and e.get("estado") == "congelado" and not e.get("abierto")]
        if not pend:
            sys.exit(f"No hay ningun congelado de {a.ultimo} pendiente de abrir en registro_holdout.json")
        a.manifiesto = pend[-1]["manifest"]
    if not a.manifiesto:
        sys.exit("Indica --manifiesto o --ultimo")
    mpath = Path(a.manifiesto)
    if not mpath.is_absolute():
        mpath = HERE / mpath
    m = json.loads(mpath.read_text(encoding="utf-8"))
    cfg = json.loads((HERE / "config.json").read_text(encoding="utf-8"))
    rel = str(mpath.relative_to(HERE)).replace("\\", "/")
    reg = json.loads(REGISTRO.read_text(encoding="utf-8")) if REGISTRO.exists() else []
    mio = next((e for e in reg if e.get("manifest") == rel), None)
    if not mio:
        sys.exit("Este manifiesto no esta en registro_holdout.json: congela con congelar.py")
    if not m.get("seleccion"):
        sys.exit("La version no tiene estrategias congeladas: no hay nada que abrir.")
    es_def = v.es_def(cfg, m["carpeta"])
    if es_def and (HERE / "CANDADO_ROTO.txt").exists():
        sys.exit("CANDADO ROTO: algo cambio desde el pre-registro (mira CANDADO_ROTO.txt). No se abre el año ciego.")
    otros = [e for e in reg if e is not mio and e.get("simbolo") == m["simbolo"] and e.get("holdout") == m["holdout"]
             and e.get("abierto")]
    if es_def:   # REGLAS_DEF: las versiones anteriores se retiran; solo cuenta si ya lo abrio otra definitiva
        otros = [e for e in otros if v.es_def(cfg, e.get("carpeta"))]
    # Rondas nuevas: el año ciego se puede volver a abrir si NINGUNA estrategia de esta version se probo ya en el.
    # Se compara la huella del codigo (sin numero magico ni fechas de exportacion).
    mis_huellas = {s["name"]: huella_codigo(mpath.parent / s["mq5"]) for s in m["seleccion"]}
    repetidas = []
    for e in otros:
        ya = huellas_de(e)
        for nombre, h in mis_huellas.items():
            if (h and h in ya["huellas"]) or v.clean_name(nombre) in ya["sin_huella"]:
                repetidas.append(f"{nombre} (ya probada por {e.get('carpeta')} el {e.get('abierto')})")
    if repetidas:
        sys.exit(f"El año ciego {m['holdout']} de {m['simbolo']} ya se uso con estas estrategias: "
                 + "; ".join(repetidas) + ". Quitalas de la seleccion o validalas en demo.")
    apertura_n = 1 + (sum(1 for e in otros if str(e["abierto"]) < str(mio["abierto"])) if mio.get("abierto")
                      else len(otros))
    if otros:
        print(f"AVISO: el año ciego {m['holdout']} de {m['simbolo']} ya se abrio {len(otros)} vez/veces "
              f"({', '.join(str(e.get('carpeta')) + ' ' + str(e.get('abierto')) for e in otros)}). "
              f"Esta es la apertura n.º {apertura_n}: las estrategias son nuevas, pero el resultado es menos fiable.")
    if a.solo_informe and not mio.get("abierto"):
        sys.exit("Este año ciego todavia no se ha abierto: no hay informe que releer.")
    if mio.get("abierto") and not a.solo_informe:
        sys.exit(f"Este año ciego ya se abrio el {mio['abierto']} (resultado: {mio.get('estado')}). "
                 "Solo se puede releer el informe con --solo-informe.")
    for s in m["seleccion"]:
        f = mpath.parent / s["mq5"]
        if sha(f) != s["sha256_mq5"]:
            sys.exit(f"{f.name} ha cambiado desde que se congelo. No se puede abrir el año ciego con una version alterada.")
    data_dir = v.find_data_folder(cfg)
    if not a.solo_informe:
        if os.name == "nt":
            if es_def and cfg.get("espera_mt5_max_horas"):
                if not v.esperar_mt5_cerrado(cfg, "año ciego"):
                    sys.exit("MetaTrader 5 sigue abierto: no se abre el año ciego. Cierralo y vuelve a lanzarlo.")
            else:
                out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq terminal64.exe"], capture_output=True, text=True).stdout
                if "terminal64.exe" in out.lower():
                    sys.exit("Cierra MetaTrader 5 antes de abrir el año ciego.")
        mio["abierto"] = datetime.now().isoformat(timespec="seconds")
        mio["estado"] = "en curso"
        mio["apertura_n"] = apertura_n
        mio["huellas_codigo"] = mis_huellas
        REGISTRO.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    d0, d1 = m["holdout"]
    tcfg = dict(cfg)
    tcfg["tester"] = {**cfg["tester"], "from_date": d0.replace("-", "."), "to_date": d1.replace("-", ".")}
    curvas, filas = {}, []
    for s in m["seleccion"]:
        name = Path(s["mq5"]).stem
        rep_name = f"HOLDOUT_{m['carpeta']}_{name}"
        rep = None
        if a.solo_informe:
            dd = data_dir / "SQX_Validador_Informes"
            rep = next((dd / (rep_name + e) for e in (".htm", ".html", ".xml") if (dd / (rep_name + e)).exists()), None)
        else:
            ex5 = v.compile_ea(cfg, data_dir, mpath.parent / s["mq5"],
                               data_dir / "MQL5" / "Experts" / "SQX_Validador" / ("HOLDOUT_" + m["carpeta"]))
            rep = v.run_tester(tcfg, data_dir, ex5, m["simbolo"], rep_name) if ex5 else None
        if not rep:
            filas.append({"estrategia": s["name"], "error": "sin informe de MT5"})
            continue
        r = v.parse_report(rep)
        eq = r.get("equity") or []
        dep = float(cfg["tester"].get("deposit", 50000))
        prev, daily = dep, {}
        for d, bal in eq:
            daily[d] = daily.get(d, 0.0) + (bal - prev)
            prev = bal
        curvas[s["name"]] = daily
        filas.append({"estrategia": s["name"], "beneficio": r.get("net_profit"), "operaciones": r.get("trades"),
                      "pf": r.get("profit_factor"), "dd": r.get("dd")})
    days = sorted(set().union(*curvas.values())) if curvas else []
    eqv = pk = ddm = 0.0
    for d in days:
        eqv += sum(c.get(d, 0.0) for c in curvas.values())
        pk = max(pk, eqv); ddm = max(ddm, pk - eqv)
    crit = m["criterio_holdout"]
    completo = all("error" not in f for f in filas)
    aprobado = completo and eqv >= crit["resultado_min"] and ddm <= crit["dd_max"]
    estado = "APROBADO" if aprobado else ("INCOMPLETO" if not completo else "SUSPENDIDO")
    res = {"abierto": mio.get("abierto"), "periodo": m["holdout"], "riesgo_por_operacion": m["riesgo"]["por_operacion"],
           "estrategias": filas, "conjunto": {"resultado": round(eqv, 2), "dd_max": round(ddm, 2)},
           "criterio": crit, "estado": estado, "apertura_n": mio.get("apertura_n", apertura_n)}
    (mpath.parent / "resultado_holdout.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    txt = [f"AÑO CIEGO {m['simbolo']} {d0} -> {d1} | version {m['version']} ({m['carpeta']}, congelada {m['congelado']})",
           f"Riesgo por operacion congelado: {m['riesgo']['por_operacion']} $"]
    n_ap = mio.get("apertura_n", apertura_n)
    if n_ap > 1:
        txt.append(f"AVISO: apertura n.º {n_ap} de este año ciego (año ciego reutilizado). Las estrategias no lo habian "
                   f"visto, pero tras {n_ap - 1} intento(s) previo(s) un APROBADO es menos fiable: alarga la demo.")
    for f in filas:
        txt.append(f"  {f['estrategia']}: " + (f["error"] if "error" in f else
                   f"{f['beneficio']} $ | {f['operaciones']} op | PF {f['pf']} | DD {f['dd']} $"))
    txt += [f"Conjunto: resultado {eqv:.2f} $ (minimo {crit['resultado_min']}) | DD {ddm:.2f} $ (maximo {crit['dd_max']})",
            f"RESULTADO: {estado}",
            (("APROBADO -> demo 2-3 meses (ejecucion) y despues real con el 50% del riesgo y corte automatico si el DD "
              "supera 1,5 x DD95." + (" " + m["nota_examen"] if m.get("nota_examen") else ""))
             if es_def else "APROBADO -> demo corta (ejecucion) y real con el riesgo congelado.") if aprobado else
            "SUSPENDIDO/INCOMPLETO -> la version se rechaza; este año ciego queda gastado (no se repite ni se quitan estrategias)."]
    (mpath.parent / "RESULTADO_AÑO_CIEGO.txt").write_text("\n".join(txt), encoding="utf-8")
    print("\n".join(txt))
    if estado != "INCOMPLETO" or not a.solo_informe:
        mio["estado"] = estado
        REGISTRO.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
