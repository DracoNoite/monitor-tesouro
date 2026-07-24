# Monitor de Preços e Taxas do Tesouro Direto

Avisa no Discord da QUAD quando um título do Tesouro atinge o preço (ou a taxa) que você definiu.

Não usa inteligência artificial, não consome tokens e não custa nada.

---

## Os arquivos

| Arquivo | Para que serve | Você mexe? |
|---|---|---|
| `metas.json` | Sua lista de títulos e alvos | **Sim, é o único** |
| `monitor.py` | O programa | Não |
| `estado.json` | Memória do que já foi avisado | Não (ele se vira) |
| `historico.csv` | Registro dos preços ao longo do tempo | Não (só consultar) |
| `webhook.txt` | O link secreto do canal do Discord | Você cria uma vez |

---

## Passo 1 — Criar o webhook do Discord (uma vez só)

O "webhook" é um link secreto que permite postar mensagens num canal, sem senha e sem bot.

1. No Discord, escolha o canal onde os alertas devem aparecer
2. Passe o mouse no nome do canal → ícone de **engrenagem** (Editar Canal)
3. Menu lateral → **Integrações**
4. **Webhooks** → botão **Novo Webhook**
5. Dê um nome (ex: `Monitor Tesouro`) e clique em **Copiar URL do Webhook**
6. Cole esse link dentro do arquivo `webhook.txt`, nesta pasta, e salve

> Esse link é uma chave: quem tiver ele consegue postar no canal. Não mande em grupo nem publique.

Para conferir se funcionou:

```bash
python monitor.py --teste-discord
```

Deve aparecer uma mensagem azul de teste no canal.

---

## Passo 2 — Definir suas metas

Abra `metas.json` no Bloco de Notas. O formato é este:

```json
{
  "banda_morta_pct": 0.5,

  "alvos": [
    {
      "titulo": "Tesouro Renda+ Aposentadoria Extra 2050",
      "apelido": "Renda+ 2050",
      "tipo": "preco",
      "metas": [500.00]
    }
  ]
}
```

**O que cada campo significa:**

- **`titulo`** — o nome **exato** como o Tesouro escreve. Não invente nem abrevie.
  Para ver a lista oficial de nomes, rode: `python monitor.py --status`
- **`apelido`** — como você quer ver escrito no alerta do Discord. Esse pode ser curto.
- **`tipo`** — `"preco"` ou `"taxa"`:
  - `"preco"` → avisa quando o preço **cair até** a meta (preço baixo = taxa alta = bom pra comprar)
  - `"taxa"` → avisa quando a taxa **subir até** a meta
- **`metas`** — uma lista. Pode ter vários degraus: `[500.00, 490.00, 480.00]`
  Cada degrau dispara seu próprio alerta, uma vez cada.
- **`banda_morta_pct`** — evita spam. Com 0.5, depois de avisar numa meta de R$ 500,
  ela só volta a valer se o preço subir acima de R$ 502,50. Sem isso, um preço
  oscilando em torno de R$ 500 encheria o canal de mensagens.

**Cuidados ao editar** (são os erros mais comuns):

- Números usam **ponto**, não vírgula: `500.00` ✅ · `500,00` ❌
- **Sem vírgula depois do último item** de uma lista
- Todo nome de título entre **aspas duplas**

Se errar, o programa te diz a linha exata do problema.

---

## Passo 3 — Usar

```bash
python monitor.py
```
Verificação normal. É isso que vai rodar sozinho de tempos em tempos.

```bash
python monitor.py --status
```
Mostra a situação de todas as suas metas e quanto falta para cada uma. **Não avisa ninguém** — pode rodar à vontade.

```bash
python monitor.py --simular
```
Finge que todas as metas bateram, só para você ver como fica o alerta no Discord.

```bash
python monitor.py --teste-discord
```
Manda uma mensagem de teste no canal.

---

## Horário de funcionamento

O Tesouro Direto negocia **das 9h30 às 18h, em dias úteis**. Fora disso o preço não muda,
então o programa nem consulta o site — ele simplesmente avisa que está fora do pregão e encerra.

A verificação roda **de 15 em 15 minutos** dentro dessa janela.

Dois detalhes de propósito:

- **A janela do programa vai até 18h30**, e não 18h. A última reprecificação do dia sai perto
  do fechamento; parar exatamente às 18h correria o risco de perdê-la.
- **Feriado não precisa de calendário.** Num feriado o preço é o mesmo do último dia útil, e
  qualquer meta que ele cruzasse já teria disparado naquele dia.

Os comandos `--status`, `--simular` e `--forcar` ignoram o horário e funcionam a qualquer momento.

---

## Como ele evita encher o saco

Cada meta tem dois estados: **armada** e **disparada**.

1. Meta armada + preço bate → **avisa** e passa para disparada
2. Enquanto disparada → fica quieta, por mais dias que o preço continue lá
3. Preço se afasta além da banda morta → **rearma** (em silêncio)
4. Preço bate de novo → avisa de novo

---

## Se algo der errado

**O programa avisa no próprio Discord quando ele mesmo quebra**, com uma mensagem
vermelha. Isso é de propósito: um alerta que morre calado é pior que não ter alerta,
porque você acha que está coberto e não está.

O motivo mais provável de quebra é o Tesouro mudar o endereço da API — já aconteceu
uma vez (a URL antiga, `treasurytitle.json`, virou página de erro). Se acontecer,
existe um plano B: o CSV oficial do Tesouro Transparente, que atualiza uma vez por dia.

---

## Fonte dos dados

`https://www.tesourodireto.com.br/o/rentabilidade/investir`

Endpoint público do site oficial do Tesouro Direto, sem login. Devolve 37 títulos
com preço unitário, taxa de compra e de venda, valor mínimo e vencimento.

Observação medida em 24/07/2026: o Tesouro **não** reprecifica de minuto em minuto.
Foi observado um intervalo de 2h14 sem qualquer mudança, com o mercado aberto. Por
isso o `historico.csv` registra cada reprecificação — depois de alguns dias dá para
saber a cadência real e ajustar a frequência de verificação com base em dado.
