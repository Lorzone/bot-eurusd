# Bot EURUSD swing (v2)

Bot di paper trading su EUR/USD, timeframe 1h–4h, che gira da solo ogni ora su GitHub (gratis) e ti avvisa su Telegram.

## Come funziona
- **Trend (4h):** compra solo se la EMA20 è sopra la EMA200, vende solo se è sotto.
- **Ingresso (1h):** a favore del trend, quando l'RSI(14) rientra sopra 30 (long) o sotto 70 (short) → si compra il ritracciamento.
- **Stop:** 2,5 × ATR(14) sull'1h (di solito 20–35 pips), poi trailing stop alla stessa distanza. Nessun take profit fisso: si lasciano correre i trade buoni.
- **Rischio:** 1% del conto per trade, una posizione alla volta. Uscita forzata dopo 120 ore.
- **Notizie:** nessun nuovo ingresso da 60 min prima a 60 min dopo una notizia ad alto impatto USD/EUR (calendario ForexFactory). Se il calendario non è disponibile, il bot non entra.
- **Regole FTMO simulate:** obiettivo +10%, perdita massima −10%, perdita giornaliera massima −5%.

## Risultati del backtest (gen 2024 – nov 2026, costi 1,3 pips inclusi)
| | Tutto il periodo | Solo dati mai visti (set 2025 → nov 2026) |
|---|---|---|
| Trade | 163 (~1,1/settimana) | 58 |
| Vinti | 46% | 48% |
| Media per trade | +0,25R | +0,17R |
| Profit factor | 1,81 | 1,68 |
| Max drawdown | −5,8% | −4,7% |

Challenge simulate (una ogni mese, rischio 1%): 20 passate, 0 bocciate, 14 ancora aperte a fine dati. In media servono ~7 mesi; con rischio 1,5% ~5 mesi.

**Limiti da sapere:**
- Il vantaggio è sottile e quasi tutto concentrato nel 2024; tra ottobre 2025 e giugno 2026 il bot è rimasto circa in pari.
- Le stesse regole su altre coppie (GBP/USD, USD/JPY, USD/CAD…) vanno in pari o perdono: è un risultato specifico di EUR/USD, non una "formula magica".
- Il filtro notizie non è nel backtest (non c'è uno storico gratuito del calendario).
- Un backtest non garantisce i risultati futuri: per questo prima si fa paper trading.

## Avvio su GitHub (10 minuti, dal telefono si può)
1. Crea un repository **privato** su GitHub e carica tutti i file di questa cartella (compresa `.github/workflows/bot.yml`).
2. *(Facoltativo, Telegram)* Su Telegram scrivi a **@BotFather** → `/newbot` → copia il token. Poi apri il tuo bot e premi **Avvia**.
   Nel repo: **Settings → Secrets and variables → Actions → New repository secret** → `TELEGRAM_TOKEN`. Il chat ID lo trova il bot da solo (opzionale: secret `TELEGRAM_CHAT_ID`).
3. Tab **Actions** → abilita i workflow → apri "bot-eurusd" → **Run workflow** per il primo giro.
4. Da lì gira da solo ogni ora (domenica–venerdì). Apri **STATUS.md** nel repo per vedere saldo, posizione aperta e prossime notizie.

*(Facoltativo)* Con un conto demo **OANDA** gratuito aggiungi il secret `OANDA_TOKEN`: il bot userà prezzi broker veri al posto di Yahoo Finance.

## File
- `live_bot.py` — il bot live (paper)
- `strategies.py` — le strategie (anche le due scartate: breakout Donchian e breakout di Londra)
- `backtest.py`, `research.py`, `multi.py` — backtest, ricerca dei parametri, test su più coppie
- `backtest_trades.csv`, `grid_results.csv` — risultati
- `state.json`, `trades.csv`, `STATUS.md` — creati dal bot mentre gira

Per provarlo sul PC: `pip install -r requirements.txt` e poi `python live_bot.py`.
