#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monitor de Taxas e Precos do Tesouro Direto
-------------------------------------------
Busca os precos/taxas do Tesouro Direto, compara com as metas definidas em
metas.json e avisa no Discord quando uma meta e atingida.

Nao usa nenhuma biblioteca externa (so o que ja vem no Python) e nao usa IA.

Como usar:
    python monitor.py                 -> roda a verificacao normal
    python monitor.py --status        -> mostra a situacao atual, sem avisar ninguem
    python monitor.py --teste-discord -> manda uma mensagem de teste no Discord
    python monitor.py --simular       -> finge que todas as metas bateram (para ver o alerta)
"""

import json
import os
import sys
import re
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Configuracoes gerais
# ---------------------------------------------------------------------------

API_TESOURO = "https://www.tesourodireto.com.br/o/rentabilidade/investir"

PASTA = os.path.dirname(os.path.abspath(__file__))
ARQ_METAS = os.path.join(PASTA, "metas.json")
ARQ_ESTADO = os.path.join(PASTA, "estado.json")
ARQ_WEBHOOK_LOCAL = os.path.join(PASTA, "webhook.txt")
ARQ_HISTORICO = os.path.join(PASTA, "historico.csv")

# Fuso de Brasilia (o Brasil nao tem mais horario de verao, entao -3 fixo esta correto)
BRT = timezone(timedelta(hours=-3))

# O Tesouro Direto negocia das 9h30 as 18h, em dias uteis.
# O fim aqui e 18h30 de proposito: a ultima reprecificacao do dia sai perto do
# fechamento, e parar exatamente as 18h correria o risco de perde-la.
ABERTURA = (9, 30)
FECHAMENTO = (18, 30)

NAVEGADOR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# Chave geral dos alertas do Discord
# ---------------------------------------------------------------------------
# DESLIGADA EM 20/08/2026 a pedido: nada sai para o Discord -- nem alerta de
# meta atingida, nem o aviso de que o proprio monitor quebrou. Todo o resto
# continua funcionando (--status, leitura da API, historico.csv).
#
# Enquanto estiver desligada, uma meta que bate NAO e marcada como "ja avisada"
# no estado.json. Assim, quando voce religar, o alerta que aconteceu no
# silencio ainda chega -- em vez de ficar perdido para sempre.
#
# PARA REATIVAR: troque para True (e descomente os gatilhos nos workflows,
# em .github/workflows/, se quiser que volte a rodar sozinho no GitHub).
# Para um teste pontual sem religar de vez, rode com ALERTAS_DISCORD=1 no
# ambiente.
ALERTAS_DISCORD = False


def alertas_ligados():
    """A chave acima, com atalho pelo ambiente para testes pontuais."""
    do_ambiente = os.environ.get("ALERTAS_DISCORD", "").strip().lower()
    if do_ambiente:
        return do_ambiente not in ("0", "false", "nao", "off")
    return ALERTAS_DISCORD


def agora_brt():
    return datetime.now(BRT)


def log(msg):
    print(f"[{agora_brt():%d/%m %H:%M:%S}] {msg}")


def dentro_do_pregao(quando=None):
    """
    Diz se o Tesouro esta negociando: dia util, entre 9h30 e 18h30.

    Isto olha o RELOGIO, nao a idade do preco. Sao coisas diferentes: fora do
    pregao o preco realmente nao pode mudar, entao pular e seguro. Ja durante o
    pregao o preco pode ficar horas parado e mesmo assim valer alerta.

    Feriado nao precisa de calendario: num feriado o preco e o mesmo do ultimo
    dia util, e qualquer meta que ele cruzasse ja teria disparado naquele dia.
    """
    quando = quando or agora_brt()
    if quando.weekday() >= 5:            # 5 = sabado, 6 = domingo
        return False
    minutos = quando.hour * 60 + quando.minute
    return ABERTURA[0] * 60 + ABERTURA[1] <= minutos <= FECHAMENTO[0] * 60 + FECHAMENTO[1]


# ---------------------------------------------------------------------------
# 1. Buscar os dados no site do Tesouro
# ---------------------------------------------------------------------------

def buscar_titulos():
    """Devolve a lista de todos os titulos disponiveis, com preco e taxa."""
    req = urllib.request.Request(
        API_TESOURO,
        headers={
            "User-Agent": NAVEGADOR,
            "Accept": "application/json",
            "Accept-Language": "pt-BR,pt;q=0.9",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resposta:
        dados = json.loads(resposta.read().decode("utf-8"))

    # O JSON vem separado em grupos ("TesouroLegado", "Tesouro24x7", ...).
    # Juntamos todos numa lista so.
    titulos = []
    for grupo in dados.values():
        if isinstance(grupo, list):
            titulos.extend(grupo)

    if not titulos:
        raise ValueError("A API respondeu, mas nao veio nenhum titulo na lista.")

    return titulos


def extrair_taxa(texto):
    """
    Transforma o texto da taxa em numero.
        'IPCA + 7,23%'      -> 7.23
        '14,41%'            -> 14.41
        'SELIC + 0,0742%'   -> 0.0742
        'SELIC'             -> 0.0
    """
    if not texto:
        return None
    achado = re.search(r"(\d+[,.]?\d*)\s*%", texto)
    if not achado:
        return 0.0
    return float(achado.group(1).replace(",", "."))


def indexador_de(texto):
    texto = (texto or "").upper()
    if "IPCA" in texto:
        return "IPCA+"
    if "SELIC" in texto:
        return "SELIC"
    return "PREFIXADO"


def normalizar(titulos):
    """Deixa cada titulo num formato simples e previsivel."""
    limpos = []
    for t in titulos:
        taxa_txt = t.get("investmentProfitabilityIndexerName")
        limpos.append({
            "nome": (t.get("treasuryBondName") or "").strip(),
            "preco": t.get("unitaryInvestmentValue"),
            "minimo": t.get("investmentBondMinimumValue"),
            "taxa_txt": taxa_txt,
            "taxa_num": extrair_taxa(taxa_txt),
            "indexador": indexador_de(taxa_txt),
            "vencimento": (t.get("maturityDate") or "")[:10],
            "precificado_em": t.get("lastMarketPricingDate"),
        })
    return limpos


def frescor(titulos):
    """
    Diz de quando sao os precos e ha quantos minutos foram calculados.

    IMPORTANTE: nao usamos isso para bloquear alertas. O Tesouro reprecifica de
    forma irregular (ja observamos 2h+ sem mudanca com o mercado aberto), entao
    tratar preco 'velho' como mercado fechado engoliria alertas de verdade.
    Quem evita aviso repetido e o estado.json, nao este relogio.
    """
    carimbos = [t["precificado_em"] for t in titulos if t.get("precificado_em")]
    if not carimbos:
        return None, None
    try:
        quando = datetime.fromisoformat(max(carimbos)).replace(tzinfo=BRT)
    except ValueError:
        return None, None
    return quando, (agora_brt() - quando).total_seconds() / 60


def registrar_historico(titulos, config):
    """
    Anota uma linha no historico.csv toda vez que o Tesouro reprecifica.
    Serve para dois fins: virar historico de precos e, principalmente, medir de
    quanto em quanto tempo o Tesouro realmente atualiza (para calibrar a
    frequencia do monitor com dado real em vez de chute).
    """
    quando, _ = frescor(titulos)
    if quando is None:
        return

    carimbo = quando.isoformat(timespec="seconds")

    # Se a ultima linha ja tem esse mesmo carimbo, nada mudou: nao repete.
    if os.path.exists(ARQ_HISTORICO):
        with open(ARQ_HISTORICO, "r", encoding="utf-8") as f:
            linhas = f.readlines()
        if len(linhas) > 1 and linhas[-1].split(";")[0] == carimbo:
            return
    else:
        with open(ARQ_HISTORICO, "w", encoding="utf-8") as f:
            f.write("precificado_em;titulo;preco;taxa\n")

    nomes = {a["titulo"] for a in config.get("alvos", [])}
    with open(ARQ_HISTORICO, "a", encoding="utf-8") as f:
        for t in titulos:
            if t["nome"] in nomes:
                f.write(f"{carimbo};{t['nome']};{t['preco']};{t['taxa_txt']}\n")


# ---------------------------------------------------------------------------
# 2. Ler as metas e a memoria do programa
# ---------------------------------------------------------------------------

def ler_json(caminho, padrao):
    """
    Le um arquivo .json.

    Usa 'utf-8-sig' de proposito: o Bloco de Notas do Windows costuma gravar uma
    marca invisivel (BOM) no inicio do arquivo, e o leitor comum quebraria com um
    erro incompreensivel. Assim funciona com ou sem a marca.
    """
    if not os.path.exists(caminho):
        return padrao
    with open(caminho, "r", encoding="utf-8-sig") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            nome = os.path.basename(caminho)
            print()
            print(f"  ERRO: o arquivo {nome} esta com um problema de digitacao.")
            print(f"  Linha {e.lineno}, coluna {e.colno}: {e.msg}")
            print()
            print("  As causas mais comuns sao:")
            print("    - virgula sobrando depois do ultimo item de uma lista")
            print("    - aspas faltando em volta do nome do titulo")
            print("    - virgula no lugar do ponto nos numeros (use 500.00, nao 500,00)")
            print()
            raise SystemExit(1)


def gravar_json(caminho, conteudo):
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump(conteudo, f, ensure_ascii=False, indent=2)


def chave_do_alvo(alvo, meta):
    return f"{alvo['titulo']}|{alvo['tipo']}|{meta}"


# ---------------------------------------------------------------------------
# 3. Decidir quem deve ser alertado
# ---------------------------------------------------------------------------

def avaliar(config, titulos, estado, simular=False):
    """
    Compara cada meta com o valor atual e devolve a lista de alertas a disparar.

    Regras:
      tipo 'preco' -> alerta quando o preco CAI ate a meta   (preco baixo = taxa alta = bom pra comprar)
      tipo 'taxa'  -> alerta quando a taxa SOBE ate a meta

    A 'banda morta' evita spam: depois de disparar, a meta so volta a ficar
    armada se o valor se afastar um pouco dela.
    """
    por_nome = {t["nome"]: t for t in titulos}
    banda = float(config.get("banda_morta_pct", 0.5)) / 100.0

    alertas = []
    nao_encontrados = []

    for alvo in config.get("alvos", []):
        titulo = por_nome.get(alvo["titulo"])
        if titulo is None:
            nao_encontrados.append(alvo["titulo"])
            continue

        tipo = alvo.get("tipo", "preco")
        atual = titulo["preco"] if tipo == "preco" else titulo["taxa_num"]
        if atual is None:
            continue

        for meta in alvo.get("metas", []):
            chave = chave_do_alvo(alvo, meta)
            ja_disparou = estado.get(chave, {}).get("disparado", False)

            if tipo == "preco":
                bateu = atual <= meta
                rearmar = atual >= meta * (1 + banda)
            else:
                bateu = atual >= meta
                rearmar = atual <= meta * (1 - banda)

            if simular:
                bateu, ja_disparou = True, False

            if bateu and not ja_disparou:
                alertas.append({"alvo": alvo, "meta": meta, "titulo": titulo, "tipo": tipo})
                estado[chave] = {
                    "disparado": True,
                    "quando": agora_brt().isoformat(timespec="seconds"),
                    "valor": atual,
                }
            elif ja_disparou and rearmar:
                estado[chave] = {"disparado": False}
                log(f"Rearmado: {alvo.get('apelido', alvo['titulo'])} meta {meta}")

    return alertas, nao_encontrados


# ---------------------------------------------------------------------------
# 4. Avisar no Discord
# ---------------------------------------------------------------------------

def url_do_webhook():
    """Pega o link do Discord do cofre do GitHub ou do arquivo local."""
    do_ambiente = os.environ.get("DISCORD_WEBHOOK", "").strip()
    if do_ambiente:
        return do_ambiente
    if os.path.exists(ARQ_WEBHOOK_LOCAL):
        with open(ARQ_WEBHOOK_LOCAL, "r", encoding="utf-8") as f:
            return f.read().strip()
    return ""


def postar_discord(payload):
    if not alertas_ligados():
        log("Alertas do Discord DESLIGADOS (ALERTAS_DISCORD = False). Nada foi enviado.")
        return False

    url = url_do_webhook()
    if not url:
        log("AVISO: nenhum webhook do Discord configurado. Nada foi enviado.")
        return False

    corpo = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=corpo,
        headers={"Content-Type": "application/json", "User-Agent": "MonitorTesouro/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return 200 <= r.status < 300
    except urllib.error.HTTPError as e:
        log(f"ERRO ao postar no Discord: HTTP {e.code} - {e.read()[:200]}")
        return False


def money(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def data_br(iso):
    """2069-12-15 -> 15/12/2069"""
    if not iso or len(iso) < 10:
        return "-"
    a, m, d = iso[:10].split("-")
    return f"{d}/{m}/{a}"


def campo_prazo(nome, vencimento):
    """
    Explica a data do titulo sem enganar ninguem.

    O Renda+ e o Educa+ nao "vencem" numa data: eles COMECAM a pagar no ano que
    esta no nome e vao pagando em parcelas por anos. O campo maturityDate da API
    e o FIM dos pagamentos. Mostrar '2069' num alerta chamado 'Renda+ 2050' faz
    o leitor achar que o robo errou -- e desconfiar dos outros alertas tambem.
    """
    ano_no_nome = re.search(r"\b(20\d{2})\b", nome or "")
    eh_parcelado = ("Renda+" in (nome or "")) or ("Educa+" in (nome or ""))

    if eh_parcelado and ano_no_nome:
        return ("Pagamentos",
                f"de {ano_no_nome.group(1)} ate {data_br(vencimento)}")
    return ("Vencimento", data_br(vencimento))


def enviar_alerta(a, simulado=False):
    t, meta, tipo = a["titulo"], a["meta"], a["tipo"]
    apelido = a["alvo"].get("apelido") or t["nome"]

    if tipo == "preco":
        titulo_msg = f"🟢 PRECO ATINGIDO — {apelido}"
        destaque = f"**{money(t['preco'])}**  ·  meta era {money(meta)}"
    else:
        titulo_msg = f"🟢 TAXA ATINGIDA — {apelido}"
        destaque = f"**{t['taxa_txt']}**  ·  meta era {meta:.2f}%"

    # Um alerta de mentira num canal de escritorio pode fazer alguem agir achando
    # que e de verdade. Simulacao TEM que ser impossivel de confundir.
    if simulado:
        titulo_msg = f"🧪 [SIMULACAO — NAO E REAL] {apelido}"
        destaque = (f"_Mensagem de teste do monitor. O alvo **nao** foi atingido._\n"
                    f"Preco real agora: **{money(t['preco'])}** · meta configurada: {money(meta)}")

    rotulo_prazo, valor_prazo = campo_prazo(t["nome"], t["vencimento"])

    bruto = t["precificado_em"] or ""
    carimbo = f"{data_br(bruto)} as {bruto[11:16]}" if len(bruto) >= 16 else "-"

    embed = {
        "title": titulo_msg,
        "description": destaque,
        "color": 0x95A5A6 if simulado else 0x2ECC71,
        "fields": [
            {"name": "Preco unitario", "value": money(t["preco"]), "inline": True},
            {"name": "Taxa de compra", "value": t["taxa_txt"] or "-", "inline": True},
            {"name": "Investimento minimo", "value": money(t["minimo"]), "inline": True},
            {"name": rotulo_prazo, "value": valor_prazo, "inline": True},
            {"name": "Titulo completo", "value": t["nome"], "inline": False},
        ],
        "footer": {"text": f"Tesouro Direto · preco calculado em {carimbo}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return postar_discord({"embeds": [embed]})


def enviar_falha(motivo):
    """Avisa no Discord que o proprio monitor quebrou (melhor que falhar calado)."""
    embed = {
        "title": "⚠️ O monitor do Tesouro falhou",
        "description": f"```{str(motivo)[:900]}```",
        "color": 0xE74C3C,
        "footer": {"text": "Verifique se a API do Tesouro mudou de endereco."},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    postar_discord({"embeds": [embed]})


# ---------------------------------------------------------------------------
# 5. Modos de uso
# ---------------------------------------------------------------------------

def modo_status(config, titulos):
    quando, idade = frescor(titulos)
    print()
    if quando is not None:
        print(f"  Ultima precificacao do Tesouro: {quando:%d/%m/%Y %H:%M} (ha {idade:.0f} minutos)")
    print()
    print(f"  {'TITULO':<38} {'ATUAL':>12} {'META':>12} {'FALTA':>10}   SITUACAO")
    print("  " + "-" * 88)

    por_nome = {t["nome"]: t for t in titulos}
    for alvo in config.get("alvos", []):
        t = por_nome.get(alvo["titulo"])
        apelido = alvo.get("apelido") or alvo["titulo"]
        if t is None:
            print(f"  {apelido:<38} {'NAO ENCONTRADO NA API':>36}")
            continue

        tipo = alvo.get("tipo", "preco")
        atual = t["preco"] if tipo == "preco" else t["taxa_num"]

        for meta in alvo.get("metas", []):
            dist = (meta - atual) / atual * 100
            bateu = atual <= meta if tipo == "preco" else atual >= meta
            situacao = "*** BATEU ***" if bateu else "aguardando"
            print(f"  {apelido:<38} {atual:>12,.2f} {meta:>12,.2f} {dist:>9.2f}%   {situacao}")

    print()
    print(f"  Total de titulos disponiveis na API: {len(titulos)}")
    print()


def main():
    args = sys.argv[1:]

    if "--teste-discord" in args:
        ok = postar_discord({
            "embeds": [{
                "title": "✅ Monitor do Tesouro conectado",
                "description": "Se voce esta lendo isso, os alertas vao chegar neste canal.",
                "color": 0x3498DB,
            }]
        })
        if ok:
            print("Mensagem de teste enviada.")
        elif not alertas_ligados():
            print("Alertas desligados (ALERTAS_DISCORD = False no monitor.py).")
            print("Para testar sem religar de vez: ALERTAS_DISCORD=1 python monitor.py --teste-discord")
        else:
            print("Falhou ao enviar. Confira o webhook.")
        return 0 if ok else 1

    config = ler_json(ARQ_METAS, {"alvos": []})

    # Fora do pregao nem chegamos a incomodar o site do Tesouro.
    # --status, --simular e --forcar passam por cima disso.
    livre = any(a in args for a in ("--status", "--simular", "--forcar"))
    if not livre and not dentro_do_pregao():
        log(f"Fora do pregao ({ABERTURA[0]}h{ABERTURA[1]:02d} as {FECHAMENTO[0]}h{FECHAMENTO[1]:02d}, "
            f"dias uteis). Nada a fazer.")
        return 0

    try:
        titulos = normalizar(buscar_titulos())
    except Exception as e:
        log(f"ERRO ao buscar dados do Tesouro: {e}")
        enviar_falha(f"Nao consegui buscar os dados do Tesouro.\n{type(e).__name__}: {e}")
        return 1

    log(f"OK: {len(titulos)} titulos recebidos da API.")

    if "--status" in args:
        modo_status(config, titulos)
        return 0

    simular = "--simular" in args
    quando, idade = frescor(titulos)
    if quando is not None:
        log(f"Precos precificados em {quando:%d/%m %H:%M} (ha {idade:.0f} min).")

    registrar_historico(titulos, config)

    estado = ler_json(ARQ_ESTADO, {})
    alertas, faltando = avaliar(config, titulos, estado, simular=simular)

    for nome in faltando:
        log(f"AVISO: o titulo '{nome}' do metas.json nao existe na API. Confira o nome exato.")

    if not alertas:
        log("Nenhuma meta atingida.")
    for a in alertas:
        apelido = a["alvo"].get("apelido") or a["titulo"]["nome"]
        log(f"{'SIMULACAO' if simular else 'ALERTA'}: {apelido} / meta {a['meta']}")
        enviar_alerta(a, simulado=simular)

    if simular:
        pass                      # simulacao nunca mexe na memoria
    elif alertas and not alertas_ligados():
        # Com os alertas desligados, gravar aqui marcaria como "ja avisado" algo
        # que ninguem recebeu -- e ao religar o aviso nunca chegaria.
        log("Estado NAO gravado: ha meta batida que ficou sem aviso (Discord desligado).")
    else:
        gravar_json(ARQ_ESTADO, estado)

    return 0


if __name__ == "__main__":
    sys.exit(main())
