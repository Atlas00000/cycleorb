//+------------------------------------------------------------------+
//| CycleORB_ExportBars.mq5 — INF-P3-T02 bar export (read-only)        |
//| Writes Common\Files\CycleORB\bars\<symbol>\<tf>\<year>.csv from    |
//| the terminal's local history (works offline), month by month so   |
//| TERMINAL_MAXBARS never truncates a request. Times = server time.  |
//| Run headless: `python -m corb bars export` (portable instance,    |
//| [StartUp] Script=CycleORB\CycleORB_ExportBars, ShutdownTerminal). |
//+------------------------------------------------------------------+
// No script_show_inputs: an input dialog would block the headless run.
input string   InpSymbols = "EURUSD,DE30,JPN225,UK100,SPX500,USDJPY,GBPUSD,Apple,Microsoft,Exxon,NVDA,Tesla";
input datetime InpFrom    = D'2020.01.01';
input datetime InpTo      = D'2026.12.31 23:59';
input string   InpFrames  = "M1,M5,H1,D1";
input int      InpWaitSec = 20;   // per monthly request while the terminal loads history from disk

ENUM_TIMEFRAMES FrameOf(const string s)
  {
   if(s == "M1") return PERIOD_M1;
   if(s == "M5") return PERIOD_M5;
   if(s == "H1") return PERIOD_H1;
   if(s == "D1") return PERIOD_D1;
   return PERIOD_CURRENT;
  }

datetime MonthStart(const int y, const int m)
  {
   return StringToTime(StringFormat("%04d.%02d.01 00:00", y, m));
  }

int CopyMonth(const string sym, const ENUM_TIMEFRAMES tf, const datetime from, const datetime to, MqlRates &r[])
  {
   int n = -1;
   for(int i = 0; i < InpWaitSec * 4 && n < 0; i++)
     {
      ResetLastError();
      n = CopyRates(sym, tf, from, to, r);
      if(n < 0)
         Sleep(250);
     }
   return n;
  }

void OnStart()
  {
   string syms[], frames[];
   const int ns = StringSplit(InpSymbols, ',', syms);
   const int nf = StringSplit(InpFrames, ',', frames);
   MqlDateTime a, b;
   TimeToStruct(InpFrom, a);
   TimeToStruct(InpTo, b);
   const int man = FileOpen("CycleORB\\bars\\manifest.csv", FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   FileWriteString(man, "symbol,tf,year,rows,first,last,digits\n");
   for(int s = 0; s < ns; s++)
     {
      const string sym = syms[s];
      if(!SymbolSelect(sym, true))
        {
         PrintFormat("EXPORT %s: symbol not available", sym);
         continue;
        }
      const int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      for(int f = 0; f < nf; f++)
        {
         const ENUM_TIMEFRAMES tf = FrameOf(frames[f]);
         for(int y = a.year; y <= b.year; y++)
           {
            int rows = 0;
            datetime first = 0, last = 0;
            int h = INVALID_HANDLE;
            for(int m = 1; m <= 12; m++)
              {
               const datetime from = MathMax(MonthStart(y, m), InpFrom);
               const datetime to = MathMin((m == 12 ? MonthStart(y + 1, 1) : MonthStart(y, m + 1)) - 1, InpTo);
               if(from > to)
                  continue;
               MqlRates r[];
               const int n = CopyMonth(sym, tf, from, to, r);
               if(n <= 0)
                  continue;
               if(h == INVALID_HANDLE)
                 {
                  h = FileOpen(StringFormat("CycleORB\\bars\\%s\\%s\\%d.csv", sym, frames[f], y),
                               FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
                  FileWriteString(h, "time,open,high,low,close,tick_volume,spread\n");
                 }
               for(int i = 0; i < n; i++)
                  FileWriteString(h, StringFormat("%s,%s,%s,%s,%s,%I64d,%d\n",
                                                  TimeToString(r[i].time, TIME_DATE | TIME_SECONDS),
                                                  DoubleToString(r[i].open, digits), DoubleToString(r[i].high, digits),
                                                  DoubleToString(r[i].low, digits), DoubleToString(r[i].close, digits),
                                                  r[i].tick_volume, r[i].spread));
               rows += n;
               if(first == 0)
                  first = r[0].time;
               last = r[n - 1].time;
              }
            if(h != INVALID_HANDLE)
              {
               FileClose(h);
               FileWriteString(man, StringFormat("%s,%s,%d,%d,%s,%s,%d\n", sym, frames[f], y, rows,
                                                 TimeToString(first, TIME_DATE | TIME_SECONDS),
                                                 TimeToString(last, TIME_DATE | TIME_SECONDS), digits));
              }
           }
         PrintFormat("EXPORT %s %s done", sym, frames[f]);
        }
     }
   FileClose(man);
   Print("EXPORT complete");
  }
