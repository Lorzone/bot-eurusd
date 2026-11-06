# Bot paper trading — gara tra 5 strategie

Cinque bot paper girano insieme ogni 30 minuti su GitHub Actions (avviati da cron-job.org), ognuno con un conto simulato da 100.000 $ e le regole di una challenge FTMO 2-Step. Dopo 2-3 mesi si sceglie quale usare nella challenge vera.

**Apri [DASHBOARD.md](DASHBOARD.md)** per il confronto: saldo, trade, risultati dal vivo contro quelli attesi, posizioni aperte, errori.

## I bot
| Bot | Cosa fa | Rischio/trade | Atteso dal backtest (lug 2024 – nov 2026) |
|---|---|---|---|
| A | Pullback EURUSD (riferimento) | 1% | 1,1 trade/sett · +0,15R · DD −7,1% |
| B | Pullback + breakout EURUSD | 0,75% | 2,1 trade/sett · +0,16R · DD −6,1% |
| C | Pullback EURUSD + GBPUSD + AUDUSD | 0,7% | 3,3 trade/sett · +0,12R · DD −8,8% |
| D | Pullback + breakout EURUSD + breakout oro | 0,75% | 3,1 trade/sett · +0,13R · DD −9,3% |
| **E** | **Nasdaq 100, continuazione prima ora (intraday: aperto e chiuso in giornata)** | 0,75% | 3,8 trade/sett · +0,11R · DD −7,5% (backtest 2020-2026) |

- **Pullback:** trend 4h (EMA20 vs EMA200) + rientro dell'RSI(14) 1h da 30/70; stop 2,5×ATR poi trailing.
- **Breakout:** chiusura 4h oltre il massimo/minimo delle ultime 10 candele 4h; stop 2,5×ATR 4h, target 3R.
- **Continuazione prima ora (E):** alle 10:30 New York (16:30 in Italia), se il Nasdaq 100 si è mosso nella prima ora di almeno 0,1 × ATR giornaliero, entra nella stessa direzione; stop all'altro estremo della prima ora; esce alle 15:55 New York (21:55 in Italia). Motore in `engine_intraday.py`, ricerca in `revisioni/2026-11-06-sera.md`.
- R = quanto si rischia su un trade. +0,15R = in media ogni trade guadagna il 15% di quanto rischia.

## Regole di protezione (uguali per tutti)
- rischio aperto massimo 1,5% (D: 2,25% in totale, max 1,5% sullo stesso strumento)
- stop giornaliero interno −3% (FTMO boccia a −5%), giornata calcolata da mezzanotte di Praga come FTMO
- rischio dimezzato se il conto è oltre il 4% sotto il massimo
- niente nuovi trade da venerdì 19:00 UTC alla riapertura; niente nuovi trade ±60 min dalle notizie ad alto impatto
- challenge simulata: passata a +10%, bocciata a −10% totale o −5% in un giorno (i bot continuano comunque, per raccogliere dati)

## File
- `run_bots.py` — esecuzione oraria · `engine.py` — motore (stesso codice per live e backtest) · `strategies.py` — strategie
- `bots/<A-D>/state.json`, `bots/<A-D>/trades.csv` — stato e storico di ogni bot
- `compare.py`, `backtest_*.csv`, `expected.json` — backtest e valori attesi
- `revisioni/` — rapporti delle revisioni notturne (idee provate, numeri, cosa è entrato o no)
- Telegram: secret `TELEGRAM_TOKEN` (il chat ID viene trovato in automatico). Dati: Yahoo Finance (oro = future GC=F); con secret `OANDA_TOKEN` usa i prezzi di un conto demo OANDA.

**Regola:** si correggono i bug, non le strategie dopo pochi trade persi. Le strategie si rivalutano con almeno 20-30 trade a testa.
