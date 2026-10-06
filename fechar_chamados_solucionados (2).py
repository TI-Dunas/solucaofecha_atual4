#!/usr/bin/env python3
"""
Fecha chamados do GLPI que estao "Solucionados" ha mais de N dias.
Pasta: /root/solucoes_glpi/solucaofecha_atual3/

As configuracoes (URL e tokens) ficam no arquivo glpi_config.ini,
na mesma pasta do script. Assim, atualizar o script nao apaga os tokens.

Uso:
    python3 fechar_chamados_solucionados.py            # simulacao (nao altera nada)
    python3 fechar_chamados_solucionados.py --executar # fecha de verdade
"""
import argparse
import configparser
import os
import sys
from datetime import datetime, timedelta

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PASTA = os.path.dirname(os.path.abspath(__file__))
ARQ_CONFIG = os.path.join(PASTA, "glpi_config.ini")
ARQ_LOG = os.path.join(PASTA, "fechamento.log")

STATUS_SOLUCIONADO, STATUS_FECHADO = 5, 6
CAMPO_ID, CAMPO_STATUS, CAMPO_DATA_SOLUCAO = 2, 12, 17


def log(msg):
    linha = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(linha)
    with open(ARQ_LOG, "a", encoding="utf-8") as f:
        f.write(linha + "\n")


def carregar_config():
    if not os.path.exists(ARQ_CONFIG):
        sys.exit(f"Arquivo de configuracao nao encontrado: {ARQ_CONFIG}")
    cfg = configparser.ConfigParser()
    cfg.read(ARQ_CONFIG, encoding="utf-8")
    g = cfg["glpi"]
    conf = {
        "url": g.get("url", "").strip().rstrip("/"),
        "app_token": g.get("app_token", "").strip(),
        "user_token": g.get("user_token", "").strip(),
        "dias": g.getint("dias", 3),
        "lote": g.getint("lote", 100),
        "verificar_ssl": g.getboolean("verificar_ssl", False),
    }
    for chave in ("url", "app_token", "user_token"):
        if not conf[chave] or conf[chave].startswith("COLE_"):
            sys.exit(f"Preencha '{chave}' em {ARQ_CONFIG}")
    return conf


def chamar(conf, metodo, caminho, headers, **kwargs):
    r = requests.request(metodo, f"{conf['url']}/{caminho}", headers=headers,
                         verify=conf["verificar_ssl"], timeout=120, **kwargs)
    if r.status_code not in (200, 201, 206):
        log(f"ERRO {r.status_code} em {caminho} - RESPOSTA DO GLPI: {r.text}")
        sys.exit(1)
    return r


def iniciar_sessao(conf):
    r = chamar(conf, "GET", "initSession",
               {"App-Token": conf["app_token"],
                "Authorization": f"user_token {conf['user_token']}"})
    return {"App-Token": conf["app_token"],
            "Session-Token": r.json()["session_token"],
            "Content-Type": "application/json"}


def buscar_solucionados(conf, headers):
    resultados, inicio, passo = [], 0, 500
    while True:
        params = {
            "criteria[0][field]": CAMPO_STATUS,
            "criteria[0][searchtype]": "equals",
            "criteria[0][value]": STATUS_SOLUCIONADO,
            "forcedisplay[0]": CAMPO_ID,
            "forcedisplay[1]": CAMPO_DATA_SOLUCAO,
            "range": f"{inicio}-{inicio + passo - 1}",
        }
        dados = chamar(conf, "GET", "search/Ticket", headers, params=params).json()
        for linha in dados.get("data", []):
            resultados.append((linha[str(CAMPO_ID)], linha.get(str(CAMPO_DATA_SOLUCAO))))
        inicio += passo
        if inicio >= int(dados.get("totalcount", 0)):
            return resultados


def fechar(conf, headers, alvos):
    fechados = falhas = 0
    for n in range(0, len(alvos), conf["lote"]):
        lote = alvos[n:n + conf["lote"]]
        corpo = {"input": [{"id": i, "status": STATUS_FECHADO} for i in lote]}
        for item in chamar(conf, "PUT", "Ticket", headers, json=corpo).json():
            msg = item.get("message", "")
            for tid, ok in item.items():
                if tid == "message":
                    continue
                if ok:
                    fechados += 1
                else:
                    falhas += 1
                    log(f"Chamado {tid}: FALHOU {msg}")
        log(f"Progresso: {min(n + conf['lote'], len(alvos))}/{len(alvos)}")
    log(f"Concluido: {fechados} fechado(s), {falhas} falha(s).")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--executar", action="store_true",
                        help="Fecha os chamados de verdade (sem isso, apenas simula)")
    args = parser.parse_args()

    conf = carregar_config()
    limite = datetime.now() - timedelta(days=conf["dias"])
    headers = iniciar_sessao(conf)
    try:
        alvos = []
        for ticket_id, data_solucao in buscar_solucionados(conf, headers):
            if data_solucao and datetime.strptime(data_solucao, "%Y-%m-%d %H:%M:%S") <= limite:
                alvos.append(ticket_id)
                print(f"Chamado {ticket_id} - solucionado em {data_solucao}")

        modo = "EXECUCAO" if args.executar else "SIMULACAO"
        log(f"[{modo}] {len(alvos)} chamado(s) solucionado(s) ha mais de {conf['dias']} dias.")
        if alvos and args.executar:
            fechar(conf, headers, alvos)
        elif alvos:
            print("Simulacao: nada foi alterado. Rode com --executar para fechar.")
    finally:
        requests.get(f"{conf['url']}/killSession", headers=headers,
                     verify=conf["verificar_ssl"], timeout=30)


if __name__ == "__main__":
    main()
