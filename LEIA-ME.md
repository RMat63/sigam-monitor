# Robô Sigam/Naturatins — instalação

O robô usa a **consulta pública** do Sigam, que não pede login nem senha, e por isso não guarda senha nenhuma. Ele roda no GitHub (grátis), de segunda a sexta, a cada 2 h, das 7 h às 19 h, e avisa no Telegram:
- 🔔 quando muda a **situação**, o **departamento** ou o assunto de um processo (mostra o antes e o depois);
- ✅ um resumo por dia quando não houve nada;
- ⚠️ quando ele próprio falha (site fora ou layout mudou). Nesse caso, falta de alerta NÃO quer dizer falta de movimentação.

Já vem configurado com 4 processos:
- 2026/40311/011248 — Colinas, LP
- 2026/40311/015485 — Colinas, AEF
- 2025/40311/012702 — Formoso do Araguaia, LP
- 2026/40311/003571 — Formoso do Araguaia, AEF

Para trocar a lista sem mexer no código, crie a **Variable** `PROCESSOS`, um processo por linha, no formato `2026/40311/011248 = Colinas – LP`.

## O que só você pode fazer (uns 10 min, dá pelo celular)

### 1. Bot do Telegram
1. No Telegram, abra **@BotFather**, mande `/newbot` e escolha nome e usuário (deve terminar em `bot`).
2. Copie o **token** que ele devolve.
3. Abra o seu bot novo e mande **oi**.

### 2. Repositório no GitHub
1. Crie uma conta em github.com, se ainda não tiver.
2. Crie um repositório **privado** chamado `sigam-monitor`.
3. Envie os arquivos `monitor.py`, `requirements.txt` e `.github/workflows/sigam.yml` (**Add file › Create new file**, digitando o caminho exato). Se preferir, autorize o acesso e o Claude envia.

### 3. Segredo
Em **Settings › Secrets and variables › Actions › New repository secret**: `TELEGRAM_TOKEN` = o token do BotFather. É o único segredo.

### 4. Primeiro teste
**Actions › Monitor Sigam › Run workflow**, modo `reconhecer`. Em uns 3 min chega no Telegram o status atual dos processos.

## Limitações conhecidas
- **A consulta pública mostra situação e departamento, não o despacho.** O conteúdo de uma pendência só aparece logado no Sigam; o alerta diz que mudou e você abre o processo para ver o quê.
- **Bloqueio de acesso de fora do Brasil:** os servidores do GitHub ficam nos EUA. Se o Sigam recusar a conexão, chega um ⚠️, e a solução é rodar o mesmo robô num servidor em São Paulo (R$ 30 a 50/mês).
- **Mudança de layout do site:** gera ⚠️, e aí o robô precisa de ajuste.
- **Intervalo:** a cada 2 h, e o GitHub pode atrasar uma execução agendada em alguns minutos.
- **GitHub:** suspende o agendamento de repositório sem atividade por 60 dias. O robô grava a leitura no repositório a cada execução, o que conta como atividade. Se mesmo assim aparecer um aviso de agendamento desativado, clique **Enable workflow** em **Actions**.
- **Complemento oficial:** a mesma tela de consulta oferece aviso de tramitação por e-mail para até 10 processos. É bom manter os dois ligados.
