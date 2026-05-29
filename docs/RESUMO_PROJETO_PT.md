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

### Por que "v2"? (decisão de arquitetura)

A primeira versão era um **"conversation flow"** — um fluxo em forma de grafo/diagrama, com nós e ramificações ("se o cliente disser X, vá para o nó Y"). Esse modelo era frágil e difícil de ajustar quando a conversa saía do roteiro. Por isso migramos para um **agente de prompt único**, que é muito mais flexível e fácil de iterar.

➡️ **Daqui pra frente, "o agente" sempre significa a Sarah v2 / prompt único.** O fluxo antigo não é mais usado.

### Como o prompt está organizado

O prompt é dividido em seções (saudação, coleta de informações, regras de agendamento, scripts de emergência, observações sobre as "tools", etc.). **Regra de ouro ao editar o prompt:** ser **enxuto e direto**. O prompt é grande e **é cobrado por token em toda ligação** — cada palavra é paga "para sempre". Não encher de texto desnecessário.

---

## 4. Como trabalhamos (Claude Code + Retell conectados)

Este é o ponto-chave do dia a dia. **Editamos o agente direto pela API da Retell, de dentro do Claude Code** — não precisamos ficar copiando e colando texto no painel da Retell na mão.

Fluxo típico de trabalho:

1. O Miguel **faz uma ligação de teste** real para a Sarah e percebe algo a melhorar ("ela disse isso", "ela devia fazer aquilo").
2. Descreve aqui no Claude Code.
3. O Claude Code **edita o prompt (ou o código do servidor)** e **publica na Retell via API**.
4. Atualiza a cópia local (`retell_agent_prompt_v2.md`) pra não dessincronizar.
5. Nova ligação de teste pra confirmar.

### Como o prompt é publicado na Retell (resumo)

O agente está **publicado** (em produção) e a Retell não deixa editar uma versão publicada diretamente. Então o processo é **criar rascunho → editar → publicar**: cria-se uma versão nova de rascunho (sem afetar o que está ao vivo), edita-se o prompt, e só então publica. O prompt fica no **LLM**; já os campos de análise e a voz ficam no **agente**. (Os detalhes completos do passo-a-passo e dos cuidados estão no `CLAUDE.md`, seção "Editing the voice agent".)

> A chave `RETELL_API_KEY` fica no arquivo `.env` (na raiz do projeto). **Nunca** subir esse arquivo pro Git.

---

## 5. As integrações em detalhe

### 5.1. Retell (a voz)
- Hospeda a Sarah. Quando alguém liga, a Retell roda o LLM e, conforme a conversa, **chama nosso backend** de duas formas:
  - **Webhooks de ciclo de vida** → `/webhook/retell` (eventos `call_started`, `call_ended`, `call_analyzed`) e `/retell/inbound` (no início da ligação, devolvemos "variáveis dinâmicas" — ver "cliente recorrente" abaixo).
  - **Tools (ferramentas customizadas)** → `/check-availability`, `/create-appointment`, `/transfer-emergency`.
- As definições das tools estão em `retell/planning/retell_tool_definitions.json`. **A Retell ignora esse arquivo em tempo de execução** — ele é só uma "fonte de cópia" pra colar no painel/usar de referência.
- **Segurança:** todos os endpoints que a Retell chama verificam uma assinatura (`X-Retell-Signature`, HMAC com a `RETELL_API_KEY`), pra impedir que alguém de fora forje agendamentos.

### 5.2. Housecall Pro (a agenda)
- É onde os agendamentos reais entram. O backend conversa com a API da HCP usando a `HCP_API_KEY`.
- **Cliente recorrente (dedupe):** no início da ligação, o backend **procura o cliente pelo número de telefone** na HCP e reaproveita o cadastro existente — em vez de criar um cliente novo a cada ligação. A Sarah confirma a identidade e o número da casa (dígito por dígito, sem ler a rua inteira em voz alta) e só pede e-mail se faltar.
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
- **Roda em 1 único processo / 1 único worker, de propósito.** O estado das ligações ao vivo fica na memória do processo. (Não é uma limitação — é uma decisão de arquitetura pra que o painel ao vivo funcione.)
- **Como fazer deploy:** editamos o `server.py` da raiz (a fonte da verdade), copiamos pra pasta `deploy/` e rodamos `railway up`. Os comandos exatos estão no `CLAUDE.md`, seção "Deploy model".

### 5.4. Dashboard (o painel)
- É uma página web servida pelo próprio backend. Acessa em `/dashboard?key=<senha>` (senha = `DASHBOARD_PASSWORD`).
- Mostra **ligações ao vivo** com transcrição em tempo real (o servidor consulta a Retell a cada ~1,5s e transmite pro navegador via **SSE** — *Server-Sent Events*).
- Tem **Central de Mensagens** (espelha os alertas), **análises** (`/analytics`) e uma aba de **on-call** (escala de plantão).
- Visual: tema escuro/ciano, com abas inferiores no celular (Calls / Insights / On-Call / Messages). Cores têm significado: **verde = ao vivo/ativo**, **vermelho `#C4080C` = identidade da marca** (logo, botão principal).

### 5.5. Telegram (os alertas)
- Bot **@hightechac_alerts_bot**, manda mensagem pro chat do Miguel (chat id `6227760301`).
- Dispara alerta quando: **ligação começa**, **ligação termina** (com resumo de quem ligou, o que foi resolvido, status, follow-up e — se houve agendamento — um texto pronto de confirmação pra copiar e mandar pro cliente) e em **transferência de emergência**.
- Token fica no `.env`/Railway (`TELEGRAM_BOT_TOKEN`). Detalhes completos em `docs/TELEGRAM_BOT_CONTEXT.md`.

### 5.6. Sistema unificado de alertas — `notify_event()`
Existe **uma única função** (`notify_event`) que dispara o mesmo alerta para **3 canais ao mesmo tempo**, com conteúdo idêntico:
1. **Telegram**
2. **Central de Mensagens** do dashboard (salva em `messages.json` + transmite ao vivo)
3. **Push no iPhone** (notificação no celular via PWA)

### 5.7. Emergências
Depois que o cliente aceita a taxa de emergência ($120), a Sarah oferece duas opções: **(a) agendar** a visita mais próxima ou **(b) transferir agora** para o técnico de plantão. Na transferência ela *oferece* (sem obrigar) coletar nome/endereço/e-mail antes. O destino é o contato de emergência definido no dashboard, com fallback para o técnico fixo de plantão.

---

## 6. Decisões importantes e por quê (histórico)

Esta seção explica **por que o sistema é do jeito que é hoje** — entender isto ajuda a não desfazer escolhas que já foram pensadas.

- **Agente de prompt único (Sarah v2):** substituiu o fluxo de nós antigo, que era frágil. Mais flexível e fácil de iterar. (Ver seção 3.)
- **Dedupe de cliente + confirmação garantida pelo servidor:** o agendamento procura o cliente pelo telefone e reaproveita o cadastro (evita clientes duplicados e endereços/e-mails errados). Além disso, o servidor **só agenda depois que a identidade é confirmada** — essa garantia fica no código, não só no prompt, porque instruções de prompt sozinhas não eram suficientes para algo tão crítico.
- **Estado persistente em `DATA_DIR`:** dados que precisam sobreviver a um redeploy (escala de plantão, mensagens, contatos de transferência) ficam no volume persistente da Railway — não em memória nem em `/tmp`.
- **Alertas unificados no `notify_event()`:** um único ponto dispara Telegram + Central de Mensagens + push, com o mesmo conteúdo, evitando duplicação e inconsistência.
- **`server.py` é fonte única da verdade:** o código de produção e o de desenvolvimento são mantidos **idênticos** (ver seção 8). A pasta `deploy/` é só o "veículo" que leva o código pra Railway.

> Os detalhes técnicos mais finos (e os cuidados de operação) ficam no `CLAUDE.md`, que é a referência para quem vai mexer no código.

---

## 7. Variáveis de ambiente (onde ficam as credenciais)

Tudo vive no `.env` (local) e nas variáveis da Railway (produção). **Nunca commitar.** As principais:

| Variável | Para quê |
|---|---|
| `HCP_API_KEY` | API da Housecall Pro |
| `RETELL_API_KEY` | API da Retell (editar prompt, ler transcrição, verificar assinatura) |
| `DASHBOARD_PASSWORD` | Senha (`?key=`) pra abrir o dashboard |
| `TELEGRAM_BOT_TOKEN` | Bot de alertas do Telegram |
| `ANTHROPIC_API_KEY` | Revisor de qualidade de ligações (IA) |
| `MIN_BOOKING_LEAD_HOURS` | Antecedência mínima pra agendamentos normais |
| `INBOUND_CONTEXT_SKIP_NUMBERS` | Números que não ouvem "bem-vindo de volta" (ex.: número de teste) |
| `DATA_DIR` | Pasta de dados persistentes (volume da Railway) |

Há um `.env.example` no repositório com a lista completa de nomes (sem valores).

---

## 8. Estrutura de pastas

```
server.py            ← O app, a FONTE DA VERDADE (idêntico ao que roda em produção)
logo.png, assets/    ← imagens servidas pelo dashboard
.env, Procfile, requirements.txt, CLAUDE.md   ← ficam na raiz (operacionais)
deploy/              ← "veículo" de deploy: repo Git separado, ligado à Railway
                       (seu server.py é mantido igual ao da raiz)
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

## 9. URLs de produção

- **Dashboard:** `https://hvac-retell-alfredo-production.up.railway.app/dashboard?key=<DASHBOARD_PASSWORD>`
- **Análises:** `/analytics?key=<DASHBOARD_PASSWORD>`
- **Webhooks da Retell:** `/webhook/retell`, `/retell/inbound`
- **Tools:** `/check-availability`, `/create-appointment`, `/transfer-emergency`
- **Saúde do servidor:** `/health`

---

## 10. Por onde começar (primeiros passos)

1. Ler **este documento** inteiro, depois o `CLAUDE.md` (versão técnica em inglês, com os detalhes de operação e deploy).
2. Pedir ao Miguel: acesso ao `.env` (credenciais), à Railway, à conta da Retell e à Housecall Pro. (As credenciais **não** vêm no repositório — são passadas à parte.)
3. Abrir o **dashboard de produção** e observar uma ligação de teste ao vivo pra ver tudo funcionando.
4. Ler o prompt atual em `retell/planning/retell_agent_prompt_v2.md`.
5. Para testar a Sarah: fazer uma **ligação real** pro número da empresa (usar o número de teste cadastrado em `INBOUND_CONTEXT_SKIP_NUMBERS` pra não ouvir "bem-vindo de volta").
6. Antes de qualquer deploy, ler a seção "Deploy model" do `CLAUDE.md`.

---

*Dúvidas → falar com o Miguel. Este projeto está ao vivo e é pago pelo cliente, então toda mudança em produção precisa de cuidado e teste.*
</content>
