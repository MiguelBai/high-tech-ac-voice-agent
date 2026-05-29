# Resumo do Projeto — High Tech AC Voice Agent (Onboarding)

> Documento de integração para quem está entrando no projeto agora. Lê do começo ao fim uma vez; depois usa como referência. Em inglês está o `CLAUDE.md` (na raiz), que é a versão técnica oficial e mais detalhada — este aqui é o panorama geral em português.

---

## 1. O que é este projeto e para quem

É uma **implementação de produção, ao vivo e paga**, para **um cliente específico**: a **High Tech Air Conditioning**, uma empresa de ar-condicionado/HVAC em **Orlando, Flórida (EUA)**.

O produto é um **agente de voz por telefone** chamado **"Sarah"** (versão atual: **Sarah v2**). Quando um cliente liga para a empresa, a Sarah atende, conversa em inglês, entende o problema (manutenção, conserto, emergência, etc.), **consulta a agenda real**, **agenda a visita do técnico** e, em emergências, **transfere a ligação** para o técnico de plantão. Tudo isso de forma automática.

**Importante:** isto **não é um template genérico**. Vários valores são fixos ("hardcoded") para a High Tech AC — IDs dos técnicos, área de atendimento, técnico de emergência, taxa de emergência ($120), horário de funcionamento, etc. Não tratar como produto reutilizável.

O que existe neste repositório é o **"cérebro de apoio"** do agente: um backend (servidor) + um painel de monitoramento. O agente de voz em si **roda na plataforma da Retell** (empresa terceira) — não roda aqui.

---

## 2. Visão geral — como tudo se conecta

```
        Cliente liga no telefone
                  │
                  ▼
        ┌─────────────────────┐
        │   RETELL AI          │  ← hospeda a "Sarah v2" (a voz, o LLM, o prompt)
        │   (plataforma de voz)│
        └──────────┬───────────┘
                   │ chama nosso backend (webhooks + "tools")
                   ▼
        ┌─────────────────────────────────────────────┐
        │   NOSSO BACKEND (server.py em Flask/Python)  │  ← roda na Railway
        │   - recebe os pedidos da Sarah               │
        │   - fala com a Housecall Pro                  │
        │   - manda alertas pro Telegram               │
        │   - alimenta o Dashboard ao vivo             │
        └───┬───────────────┬───────────────┬──────────┘
            │               │               │
            ▼               ▼               ▼
   ┌──────────────┐  ┌────────────┐  ┌──────────────┐
   │ HOUSECALL PRO│  │  TELEGRAM  │  │  DASHBOARD    │
   │ (agenda real │  │  (alertas  │  │  (painel ao   │
   │  + clientes) │  │  no celular)│  │  vivo no nav.)│
   └──────────────┘  └────────────┘  └──────────────┘
```

As 5 peças externas:

| Peça | O que é | Papel no projeto |
|---|---|---|
| **Retell AI** | Plataforma de agentes de voz por telefone | Hospeda a Sarah. É quem realmente atende a ligação e "pensa". |
| **Housecall Pro (HCP)** | Software de gestão de campo (clientes, agenda, técnicos) | Onde os agendamentos reais acontecem. Nossa "fonte da verdade" da agenda. |
| **Railway** | Hospedagem do nosso servidor (cloud) | Onde o `server.py` roda 24/7 em produção. |
| **Telegram** | App de mensagens | Recebe alertas em tempo real (ligação chegou, ligação terminou, emergência). |
| **Dashboard** | Página web servida pelo próprio backend | Painel ao vivo: ligações em tempo real, transcrição, central de mensagens, análises. |

E a peça interna mais importante:

| Peça | O que é |
|---|---|
| **Claude Code** | A ferramenta (este ambiente) que usamos para editar o código, o prompt da Sarah e fazer os deploys. É como trabalhamos no dia a dia. |

---

## 3. O agente de voz "Sarah v2"

### O que é hoje

A Sarah v2 é um agente de **prompt único** (*single-prompt*). Ou seja: **todo o comportamento dela está escrito em um único texto grande** (o "prompt"), que é entregue ao LLM a cada ligação.

- **ID do agente (Retell):** `agent_0d457978dd795971fabfb1cdb6`
- **ID do LLM (Retell):** `llm_3f1ab929b9b566f0a1a4be12ecfb` — é aqui que o prompt (`general_prompt`) vive.
- **Cópia local do prompt:** `retell/planning/retell_agent_prompt_v2.md` — sempre mantemos esse arquivo igual ao que está publicado na Retell, pra não "dessincronizar".

### Por que "v2"? (decisão importante)

A **primeira versão era um "conversation flow"** — um fluxo em forma de grafo/diagrama, com nós e ramificações ("se o cliente disser X, vá para o nó Y"). **Esse modelo não funcionou bem:** era frágil, difícil de ajustar e quebrava em conversas fora do roteiro.

Trocamos tudo por um **agente de prompt único**, que é muito mais flexível e fácil de iterar. **Daqui pra frente, "o agente" sempre significa a Sarah v2 / prompt único.** Não mexer nem ressuscitar o fluxo antigo.

### Como o prompt está organizado

O prompt é dividido em seções (saudação, coleta de informações, regras de agendamento, scripts de emergência, observações sobre as "tools", etc.). **Regra de ouro ao editar o prompt:** ser **enxuto e direto**. O prompt é grande e **é cobrado por token em toda ligação** — cada palavra é paga "para sempre". Não encher de texto desnecessário.

---

## 4. Como trabalhamos (Claude Code + Retell conectados)

Este é o ponto-chave do dia a dia. **Editamos o agente direto pela API da Retell, de dentro do Claude Code** — não precisamos ficar copiando e colando texto no painel da Retell na mão.

Fluxo típico de trabalho:

1. O Miguel **faz uma ligação de teste** real para a Sarah e percebe um problema ("ela disse algo errado", "ela não devia fazer X", "ela alucinou um endereço").
2. Descreve o problema aqui no Claude Code.
3. O Claude Code **edita o prompt (ou o código do servidor)** e **publica na Retell via API**.
4. Atualiza a cópia local (`retell_agent_prompt_v2.md`) pra não dessincronizar.
5. Nova ligação de teste pra confirmar.

### Detalhe técnico do fluxo de edição do prompt na Retell

O agente está **publicado** (em produção), e a Retell **não deixa editar uma versão publicada diretamente** (dá erro HTTP 400 "Cannot update published LLM"). Então o processo é **criar rascunho → editar → publicar**:

1. `POST create-agent-version/{agent_id}` → cria um **rascunho** novo (não afeta o tráfego ao vivo).
2. `GET get-retell-llm/{llm_id}` → pega o prompt atual do rascunho.
3. `PATCH update-retell-llm/{llm_id}` → edita o prompt no rascunho.
4. `POST publish-agent/{agent_id}` → publica e vira o que está ao vivo.
5. Espelha a mudança no arquivo local.

**Cuidados (já nos morderam):**
- A versão do agente e a versão do LLM são **acopladas 1:1** (agente vN ↔ LLM vN).
- Os comandos `get-*` retornam a **última** versão (que pode ser um rascunho novo), **não necessariamente a que está ao vivo**. Sempre **verificar qual está publicada** (`get-agent-versions`, campo `is_published`) — não confiar no número que você passou.
- Usar **`curl`, não Python urllib** (a urllib dá erro de certificado `CERTIFICATE_VERIFY_FAILED` nesta máquina).
- O prompt fica no **LLM** (`update-retell-llm`); já os campos de análise e a configuração de voz ficam no **agente** (`update-agent`).

> A chave `RETELL_API_KEY` fica no arquivo `.env` (na raiz do projeto). **Nunca** subir esse arquivo pro Git.

---

## 5. As integrações em detalhe

### 5.1. Retell (a voz)
- Hospeda a Sarah. Quando alguém liga, a Retell roda o LLM e, conforme a conversa, **chama nosso backend** de duas formas:
  - **Webhooks de ciclo de vida** → `/webhook/retell` (eventos `call_started`, `call_ended`, `call_analyzed`) e `/retell/inbound` (no início da ligação, devolvemos "variáveis dinâmicas" — ver dedupe abaixo).
  - **Tools (ferramentas customizadas)** → `/check-availability`, `/create-appointment`, `/transfer-emergency`.
- As definições das tools estão em `retell/planning/retell_tool_definitions.json`. **A Retell ignora esse arquivo em tempo de execução** — ele é só uma "fonte de cópia" pra colar no painel/usar de referência.
- **Verificação de assinatura:** todos os 5 endpoints que a Retell chama verificam o cabeçalho `X-Retell-Signature` (HMAC com a `RETELL_API_KEY`), pra impedir que alguém de fora forje agendamentos. Hoje está em modo **`monitor`** (só registra, não bloqueia). Falta virar pra **`enforce`** depois de confirmar nos logs que todos os 5 endpoints estão assinando corretamente.

### 5.2. Housecall Pro (a agenda)
- É onde os agendamentos reais entram. O backend conversa com a API da HCP usando a `HCP_API_KEY`.
- **Regras de agendamento (fixas no código):**
  - Fuso de Orlando: `America/New_York`. A HCP devolve em UTC; convertemos tudo pro horário local.
  - Horário de atendimento: **6h–22h, todos os dias**, janelas de chegada de **2 horas**, busca de até **7 dias** à frente.
  - Agendamentos normais exigem **12h de antecedência** (`MIN_BOOKING_LEAD_HOURS`).
  - `FIELD_TECHS`: lista fixa de IDs de técnicos; o sistema pega o **primeiro técnico livre** no horário pedido.
  - `DO_NOT_BOOK_SERVICES = ["duct cleaning"]` (limpeza de duto **não** é agendada — vira pedido de retorno/callback).
  - `SERVICE_AREA`: lista fixa; fora da área = resposta amigável de "vamos te retornar".
  - E-mail é exigido no agendamento (a não ser que o cliente já tenha um no cadastro).

### 5.3. Railway (a hospedagem)
- O `server.py` roda na Railway, no serviço **`HVAC Retell Alfredo`**.
- **Roda em 1 único processo / 1 único worker, de propósito.** O estado das ligações ao vivo fica na memória do processo. **Não aumentar o número de workers** — isso quebraria o painel ao vivo (SSE) e o registro compartilhado de ligações.
- Como fazer deploy está na seção 7 (tem uma pegadinha importante).

### 5.4. Dashboard (o painel)
- É uma página web servida pelo próprio backend. Acessa em `/dashboard?key=<senha>` (senha = `DASHBOARD_PASSWORD`).
- Mostra **ligações ao vivo** com transcrição em tempo real (o servidor consulta a Retell a cada ~1,5s e transmite pro navegador via **SSE** — *Server-Sent Events*).
- Tem **Central de Mensagens** (espelha os alertas), **análises** (`/analytics`) e uma aba de **on-call** (escala de plantão).
- Visual: tema escuro/ciano, com abas inferiores no celular (Calls / Insights / On-Call / Messages). Cores têm significado: **verde = ao vivo/ativo**, **vermelho `#C4080C` = identidade da marca** (logo, botão principal). Não misturar os dois.

### 5.5. Telegram (os alertas)
- Bot **@hightechac_alerts_bot**, manda mensagem pro chat do Miguel (chat id `6227760301`).
- Dispara alerta quando: **ligação começa**, **ligação termina** (com resumo de quem ligou, o que foi resolvido, status, follow-up e — se houve agendamento — um texto pronto de confirmação pra copiar e mandar pro cliente) e em **transferência de emergência**.
- Token fica no `.env`/Railway (`TELEGRAM_BOT_TOKEN`). Detalhes completos em `docs/TELEGRAM_BOT_CONTEXT.md`.

### 5.6. Sistema unificado de alertas — `notify_event()`
Existe **uma única função** (`notify_event`) que dispara o mesmo alerta para **3 canais ao mesmo tempo**, com conteúdo idêntico:
1. **Telegram**
2. **Central de Mensagens** do dashboard (salva em `messages.json` + transmite ao vivo)
3. **Push no iPhone** (notificação no celular via PWA)

> ⚠️ Não recriar avisos no lado do navegador (client-side push) para `call_started`/`call_analyzed` — isso já foi removido. Se voltar, gera **alertas duplicados**.

---

## 6. Problemas que encontramos e como resolvemos

Esta seção é o "histórico de guerra". Entender isto evita repetir os mesmos erros.

### 6.1. O fluxo antigo (conversation flow) não funcionava
- **Problema:** a v1 era um grafo de nós, frágil e difícil de ajustar.
- **Solução:** reescrevemos como **agente de prompt único** (Sarah v2). Muito mais flexível.

### 6.2. Cliente duplicado e endereço/e-mail inventados (o maior bug)
- **Problema:** a função `create_appointment` **criava um cliente novo na HCP toda ligação**, sem procurar se ele já existia. Resultado: para um mesmo número de teste, **acumularam 9 cadastros duplicados**; e em clientes recorrentes a Sarah **alucinava o endereço do escritório** (6148 Hanging Moss Rd) e **inventava um e-mail**.
- **Solução:** no início da ligação (`/retell/inbound`), passamos a **procurar o cliente pelo número de telefone** na HCP (em paralelo, com prazo de 2,5s) e devolver os dados dele. A Sarah confirma a identidade e o número da casa (dígito por dígito, sem ler a rua inteira em voz alta), só pede e-mail se faltar, e o `create_appointment` **reaproveita** o cadastro existente em vez de criar outro.

### 6.3. Confirmar só pelo prompt não bastava
- **Problema:** mesmo instruída no prompt a confirmar a identidade antes de agendar, a Sarah **continuava agendando em silêncio** (falhou 3 vezes seguidas).
- **Solução:** **forçamos no servidor.** Agora, se existe um perfil encontrado, o `create_appointment` **se recusa a agendar** a menos que o agente envie `profile_confirmed: true`. Caso contrário, devolve uma instrução pra Sarah perguntar e tentar de novo. Regra que importa: não dá pra confiar só no prompt para coisas críticas — o servidor precisa garantir.
- **Pendência:** os 9 duplicados antigos do número de teste **ainda não foram limpos** (a limpeza foi adiada pelo Miguel). Enquanto isso, a busca pega o cadastro mais recente e o passo de confirmação corrige.

### 6.4. Alertas migraram de Twilio (SMS) → Telegram → unificado
- **Problema:** os alertas começaram via **Twilio (SMS)**, que era limitado/caro.
- **Solução:** trocamos por **Telegram**, e depois unificamos tudo no `notify_event()` (Telegram + Central de Mensagens + push no iPhone).
- ⚠️ **Cuidado que sobrou:** o `server.py` da pasta **`deploy/` já usa Telegram**, mas o `server.py` da **raiz ainda usa o Twilio antigo** (ver seção 7 — divergência).

### 6.5. Escala de plantão era apagada a cada deploy
- **Problema:** a escala de on-call era salva em `/tmp`, que a Railway **apaga a cada redeploy**. Por isso a Sarah "ignorava" o técnico de plantão escolhido.
- **Solução:** passamos a salvar no `DATA_DIR` (volume persistente da Railway).

### 6.6. Alertas do Telegram não chegavam
- **Problema:** dois motivos — (1) token/chat_id **de placeholder** no `.env`/Railway; (2) **imagem velha** rodando na Railway (ainda com o código do Twilio).
- **Solução:** colocar os valores reais e **fazer o deploy de verdade** (ver recipe na seção 7).

### 6.7. Bugs menores de dashboard
- **SVG sem classe** renderizava no tamanho padrão 300×150 do navegador e estourava o layout. Solução: todo ícone SVG **precisa** de `class="icon|icon-sm|icon-xs"`, e existe um CSS defensivo de fallback.
- **Push duplicado:** alertas chegavam em dobro porque havia push no servidor **e** no navegador. Solução: removemos o push do lado do navegador.

---

## 7. Erros que ainda podem acontecer (pontos de atenção)

Leia com atenção — são as armadilhas ativas do projeto.

### 7.1. ⚠️ A pegadinha mais perigosa: divergência entre `deploy/` e a raiz
Existem **dois repositórios Git na mesma pasta**:
- **Raiz** (`./.git`) → workspace de desenvolvimento. **Está ATRASADO** e o `server.py` da raiz ainda usa **Twilio**, sem os subsistemas novos.
- **`deploy/`** (`deploy/.git`) → **é o código que realmente roda em produção** (~7,5 mil linhas, com Telegram, Central de Mensagens, push, lookup de cliente, verificação de assinatura, etc.).

➡️ **NUNCA fazer `cp server.py deploy/server.py` (cópia cega).** Isso **reverteria a produção** pro código antigo do Twilio e destruiria todo o trabalho de notificações/transferência/push. **Toda mudança deve ser feita no `deploy/server.py`** (e, se quiser, espelhada na raiz). Algum dia os dois devem ser unificados num só.

### 7.2. ⚠️ `railway up` trava em "Indexing..."
- Rodar `railway up` direto de dentro de `deploy/` **trava para sempre** em "Indexing...", porque ele tropeça nas pastas `.worktrees/` e `.git` aninhadas.
- **Solução (recipe de deploy limpo):** copiar só os arquivos de runtime pra uma pasta limpa e fazer o deploy de lá:
  ```bash
  mkdir -p /tmp/hvac-clean-deploy
  cp deploy/server.py deploy/Procfile deploy/requirements.txt deploy/logo.png /tmp/hvac-clean-deploy/
  cp -r deploy/assets /tmp/hvac-clean-deploy/
  cd deploy && git add -A && git commit -m "..."
  railway up "/tmp/hvac-clean-deploy" --path-as-root --service "HVAC Retell Alfredo" --ci
  ```
- Conferir depois com `railway logs --service "HVAC Retell Alfredo"`.

### 7.3. Outros riscos
- **Verificação de assinatura** ainda está em `monitor` — falta virar pra `enforce` (os endpoints estão "abertos" até lá).
- **9 cadastros duplicados** do número de teste ainda não foram limpos na HCP.
- **Não aumentar workers** na Railway (quebra o painel ao vivo).
- **Version drift na Retell** — sempre confirmar qual versão está realmente publicada.
- **`urllib` falha por certificado** — usar `curl` para a API da Retell.
- **Segredos só vivem no `.env` e na Railway** — nunca commitar `.env`.

---

## 8. Variáveis de ambiente (onde ficam as credenciais)

Tudo vive no `.env` (local) e nas variáveis da Railway (produção). **Nunca commitar.** As principais:

| Variável | Para quê |
|---|---|
| `HCP_API_KEY` | API da Housecall Pro |
| `RETELL_API_KEY` | API da Retell (editar prompt, ler transcrição, verificar assinatura) |
| `DASHBOARD_PASSWORD` | Senha (`?key=`) pra abrir o dashboard |
| `TELEGRAM_BOT_TOKEN` | Bot de alertas do Telegram |
| `ANTHROPIC_API_KEY` | Revisor de qualidade de ligações (IA) |
| `RETELL_VERIFY_MODE` | `off`/`monitor`/`enforce` da verificação de assinatura |
| `MIN_BOOKING_LEAD_HOURS` | Antecedência mínima pra agendamentos normais |
| `INBOUND_CONTEXT_SKIP_NUMBERS` | Números que não ouvem "bem-vindo de volta" (ex.: número de teste) |
| `DATA_DIR` | Pasta de dados persistentes (volume da Railway) |

---

## 9. URLs de produção

- **Dashboard:** `https://hvac-retell-alfredo-production.up.railway.app/dashboard?key=<DASHBOARD_PASSWORD>`
- **Análises:** `/analytics?key=<DASHBOARD_PASSWORD>`
- **Webhooks da Retell:** `/webhook/retell`, `/retell/inbound`
- **Tools:** `/check-availability`, `/create-appointment`, `/transfer-emergency`
- **Saúde do servidor:** `/health`

---

## 10. Estrutura de pastas

```
server.py            ← app do workspace (NÃO é o que a Railway roda — ver seção 7)
logo.png, .env, Procfile, requirements.txt, CLAUDE.md   ← ficam na raiz (operacionais)
deploy/              ← CÓDIGO QUE RODA EM PRODUÇÃO + seu próprio repo Git
data/                ← estado local (SQLite + json)

knowledge_base/      base de conhecimento da empresa (txt)
proposals/
  ├─ deliverables/   PDFs entregues ao cliente (proposta, contrato, formulário)
  └─ generators/     scripts que geram esses PDFs
retell/
  ├─ planning/       prompt v2, definições das tools, PDFs de fluxo, suíte de simulações
  └─ generators/     scripts de geração de fluxo
docs/                pesquisa de mercado, notas de deploy, contexto do Telegram,
                     planos de teste, e ESTE resumo
```

---

## 11. Por onde começar (primeiros passos)

1. Ler **este documento** inteiro, depois o `CLAUDE.md` (versão técnica em inglês).
2. Pedir ao Miguel: acesso ao `.env` (credenciais), à Railway, à conta da Retell e à Housecall Pro.
3. Abrir o **dashboard de produção** e observar uma ligação ao vivo de teste pra ver tudo funcionando.
4. Ler o prompt atual em `retell/planning/retell_agent_prompt_v2.md`.
5. Antes de qualquer deploy: reler a **seção 7** (as duas pegadinhas) — é onde mais se erra.
6. Para testar a Sarah: fazer uma **ligação real** pro número da empresa (usar o número de teste cadastrado em `INBOUND_CONTEXT_SKIP_NUMBERS` pra não ouvir "bem-vindo de volta").

---

*Dúvidas → falar com o Miguel. Este projeto está ao vivo e é pago pelo cliente, então toda mudança em produção precisa de cuidado e teste.*
</content>
