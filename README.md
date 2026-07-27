# Monitor de Preços e Taxas do Tesouro Direto

Avisa em um canal do Discord quando um título do Tesouro Direto atinge o preço ou a taxa que você definiu.

Roda sozinho no GitHub Actions, de 15 em 15 minutos, em dias úteis das 9h30 às 18h30. Não usa nenhuma
biblioteca externa — só a biblioteca padrão do Python — e não depende de nenhum serviço pago.

```
🟢 PREÇO ATINGIDO — Renda+ 2050
   R$ 498,20  ·  meta era R$ 500,00

   Preço unitário     Taxa de compra     Investimento mínimo
   R$ 498,20          IPCA + 7,31%       R$ 4,98

   Pagamentos
   de 2050 até 15/12/2069
```

---

## Como funciona

1. Um cron externo acorda o GitHub Actions de 15 em 15 minutos dentro do pregão (veja [Agendamento](#agendamento))
2. O script consulta a API pública do Tesouro Direto
3. Compara os 37 títulos disponíveis com as metas do `metas.json`
4. Se alguma meta foi cruzada, posta um aviso no Discord via webhook
5. Grava no repositório o que já foi avisado, para não repetir

---

## Configuração

Toda a configuração vive em [`metas.json`](metas.json):

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

| Campo | Descrição |
|---|---|
| `titulo` | Nome exato como o Tesouro publica. Veja a lista com `python monitor.py --status` |
| `apelido` | Nome curto que aparece no alerta |
| `tipo` | `preco` avisa quando o preço **cai** até a meta · `taxa` avisa quando a taxa **sobe** até a meta |
| `metas` | Lista de degraus. `[500, 490, 480]` dispara três alertas independentes |
| `banda_morta_pct` | Quanto o valor precisa se afastar para a meta rearmar. Evita alertas repetidos quando o preço oscila em torno do alvo |

Os dois tipos apontam para o mesmo evento — o título ficou mais atrativo — só que medido por
ângulos diferentes. Em `tipo: "taxa"`, escreva apenas o número: `7.60` significa *IPCA + 7,60%*.

### Como os alertas evitam virar spam

Cada meta tem dois estados: **armada** e **disparada**.

1. Meta armada + valor cruza o alvo → avisa e passa para disparada
2. Enquanto disparada, fica em silêncio, por mais dias que a condição persista
3. O valor se afasta além da banda morta → rearma, sem avisar
4. Cruza de novo → avisa de novo

---

## Uso local

```bash
python monitor.py --status         # situação de todas as metas, sem avisar ninguém
python monitor.py --teste-discord  # mensagem de teste no canal
python monitor.py --simular        # alerta de exemplo, marcado como simulação
python monitor.py --forcar         # roda ignorando o horário do pregão
```

O modo `--simular` marca a mensagem como **[SIMULAÇÃO — NÃO É REAL]** de propósito: um alerta
falso de "preço atingido" num canal de trabalho pode levar alguém a agir achando que é verdadeiro.

---

## Instalação

1. Faça um fork ou clone deste repositório
2. Crie um webhook no canal do Discord (*Editar canal → Integrações → Webhooks → Novo Webhook*)
3. No repositório: **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `DISCORD_WEBHOOK`
   - Secret: a URL do webhook
4. Ajuste o `metas.json`

Para rodar localmente, coloque a URL do webhook num arquivo `webhook.txt` na raiz. Ele está no
`.gitignore` e nunca é enviado ao repositório.

---

## Agendamento

O `schedule` nativo do GitHub Actions é *melhor esforço*: em horário de pico o GitHub simplesmente
descarta a execução, sem aviso. Neste repositório ele deixou de rodar em cerca de **94%** das vezes.
Um monitor que acorda em 1 de cada 16 janelas é pior do que não ter monitor, porque passa uma
sensação de cobertura que não existe.

Por isso o gatilho principal é um **cron externo** que chama a API do GitHub e dispara o evento
`repository_dispatch`. O `schedule` continua no workflow, rebaixado a rede de segurança.

### 1. Criar o token

Em [github.com/settings/personal-access-tokens/new](https://github.com/settings/personal-access-tokens/new):

| Campo | Valor |
|---|---|
| Repository access | *Only select repositories* → `monitor-tesouro` |
| Permissions → Repository → Contents | **Read and write** |
| Expiration | o prazo que você aceitar renovar (máximo de 1 ano) |

Prefira o token *fine-grained* ao clássico: o clássico com escopo `public_repo` daria escrita em
**todos** os seus repositórios públicos, e aqui basta um.

`Contents: Read and write` é o mínimo — `repository_dispatch` exige escrita, não existe permissão
mais estreita só para disparar eventos.

### 2. Testar antes de agendar

Grave o token em `token-github.txt` na raiz (está no `.gitignore`) e rode:

```powershell
.\disparar.ps1
```

Um token sem permissão devolve **404**, não 403 — o GitHub esconde de propósito a existência dos
repositórios que o token não enxerga. Não perca tempo procurando erro de digitação no nome do
repositório: quase sempre o problema é a permissão.

### 3. Configurar o cron externo

Em [cron-job.org](https://cron-job.org) (gratuito, aceita POST com cabeçalhos próprios), crie um job:

| Campo | Valor |
|---|---|
| URL | `https://api.github.com/repos/DracoNoite/monitor-tesouro/dispatches` |
| Método | `POST` |
| Fuso horário | `America/Sao_Paulo` |
| Dias | segunda a sexta |
| Horas | 9 às 18 |
| Minutos | 0, 15, 30, 45 |

Cabeçalhos:

```
Accept: application/vnd.github+json
Authorization: Bearer SEU_TOKEN_AQUI
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json
```

Corpo:

```json
{"event_type":"verificar"}
```

A janela cobre 09h00–18h45, um pouco mais larga que o pregão de propósito. As sobras não custam
nada: o `monitor.py` se recusa a agir fora do horário e sai em segundos, sem sequer chamar o
Tesouro. O mesmo raciocínio já vale para o `schedule` do workflow.

**Ligue a notificação de falha do cron-job.org.** Quando o token expirar, o job passa a receber 401
e para de acordar o monitor — em silêncio, porque quem falhou foi o cron, não o programa. O aviso
vermelho no Discord não cobre esse caso: ele só existe quando o monitor chega a rodar.

### O que a API responde

`204 No Content` significa *recebi o pedido*, não *o monitor rodou*. A execução em si aparece em
[Actions](https://github.com/DracoNoite/monitor-tesouro/actions).

O `repository_dispatch` só funciona com o workflow presente no **branch padrão** — em outro branch,
o GitHub aceita o disparo com 204 e não roda nada.

---

## Fonte dos dados

```
https://www.tesourodireto.com.br/o/rentabilidade/investir
```

Endpoint público do site oficial, sem autenticação. Devolve 37 títulos com preço unitário, taxa
de compra e de venda, investimento mínimo e vencimento.

Duas observações que custaram tempo para descobrir e podem poupar o seu:

- **A API antiga morreu.** O endereço `.../service/api/treasurytitle.json`, que ainda aparece em
  muitos tutoriais, retorna 404. O endpoint acima é o que responde hoje.
- **O JSON vem em dois grupos.** `TesouroLegado` traz 36 títulos e `Tesouro24x7` traz 1
  (o Tesouro Reserva). Quem lê apenas o primeiro perde um título silenciosamente.
- **O Tesouro não reprecifica de minuto em minuto.** Em 24/07/2026 foi observado um intervalo de
  2h14 sem qualquer mudança, com o mercado aberto. Verificar a cada 5 minutos não antecipa nada —
  só multiplica requisições. O `historico.csv` registra cada reprecificação justamente para medir
  essa cadência com dado, e não com estimativa.

---

## Estrutura

| Arquivo | Papel |
|---|---|
| `monitor.py` | Todo o programa |
| `metas.json` | Configuração dos alvos |
| `disparar.ps1` | Dispara uma verificação na hora e testa o token do cron externo |
| `estado.json` | Memória de quais alertas já dispararam |
| `historico.csv` | Registro dos preços a cada reprecificação |
| `.github/workflows/monitor.yml` | Agendamento e persistência do estado |

---

## Detalhes de implementação

Alguns cuidados que não são óbvios de fora:

- **A data do Renda+ e do Educa+ engana.** O campo `maturityDate` do Renda+ 2050 vale `2069-12-15`:
  o título *começa* a pagar em 2050 e paga por 20 anos. Exibir isso como "Vencimento" faz o leitor
  achar que o programa errou, então o alerta mostra "Pagamentos de 2050 até 15/12/2069".
- **A janela do pregão vai até 18h30, não 18h.** A última reprecificação do dia sai perto do
  fechamento; parar às 18h em ponto arriscaria perdê-la.
- **Feriado não precisa de calendário.** Num feriado o preço é o do último dia útil, e qualquer
  meta que ele cruzasse já teria disparado naquele dia.
- **O horário é verificado pelo relógio, nunca pela idade do preço.** Tratar preço "velho" como
  mercado fechado engoliria alertas legítimos, já que o Tesouro passa horas sem reprecificar.
- **Falha não é silenciosa.** Se o programa não conseguir buscar os dados, ele posta um aviso
  vermelho no próprio Discord. Um alerta que morre calado é pior que não ter alerta, porque passa
  a sensação de cobertura que não existe.
- **A configuração é lida com `utf-8-sig`.** O Bloco de Notas do Windows grava um BOM invisível
  que quebraria a leitura com um erro incompreensível para quem não programa.

---

## Licença

Uso livre.
