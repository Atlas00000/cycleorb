//+------------------------------------------------------------------+
//| CycleORB_ExportBars.mq5 — INF-P3-T02 bar export (read-only)        |
//| Writes Common\Files\CycleORB\bars\<symbol>\<tf>\<year>.csv from    |
//| the terminal's local history (works offline). Requests go month by |
//| month (TERMINAL_MAXBARS never truncates one) from the newest month |
//| backwards and stop after two empty months once data was found, so |
//| nothing waits on history that does not exist. A history gap      |
//| therefore ends the export for that series. Times = server time.   |
//| Run headless: `python -m corb bars export`.                       |
//+------------------------------------------------------------------+
// No script_show_inputs: an input dialog would block the headless run.
input string   InpSymbols = "EURUSD,DE30,JPN225,UK100,SPX500,USDJPY,GBPUSD,Apple,Microsoft,Exxon,NVDA,Tesla";
input datetime InpFrom    = D'2020.01.01';
input datetime InpTo      = D'2026.12.31 23:59';
input string   InpFrames  = "M1,M5,H1,D1";
input int      InpWaitSec = 3;    // per monthly request while the terminal loads history from disk

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
      n = CopyRates(sym, tf, from, to, r);
      if(n < 0)
         Sleep(250);
     }
   return n;
  }

struct MonthBars
  {
   MqlRates          r[];
  };

// One year of one series, months collected newest first; returns false once the series has ended (going back)
bool ExportYear(const string sym, const ENUM_TIMEFRAMES tf, const string frame, const int y, const int digits,
                bool &found, int &misses, const int man)
  {
   MonthBars months[12];
   int counts[12];
   ArrayInitialize(counts, 0);
   bool more = true;
   for(int m = 12; m >= 1 && more; m--)
     {
      const datetime from = MathMax(MonthStart(y, m), InpFrom);
      const datetime to = MathMin((m == 12 ? MonthStart(y + 1, 1) : MonthStart(y, m + 1)) - 1, InpTo);
      if(from > to || from > TimeCurrent())
         continue;
      MqlRates r[];
      const int n = CopyMonth(sym, tf, from, to, r);
      if(n > 0)
        {
         ArrayCopy(months[m - 1].r, r);
         counts[m - 1] = n;
         found = true;
         misses = 0;
        }
      else if(found && ++misses >= 2)
         more = false;
     }
   int rows = 0;
   for(int m = 0; m < 12; m++)
      rows += counts[m];
   if(rows > 0)
     {
      const int h = FileOpen(StringFormat("CycleORB\\bars\\%s\\%s\\%d.csv", sym, frame, y),
                             FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
      FileWriteString(h, "time,open,high,low,close,tick_volume,spread\n");
      datetime first = 0, last = 0;
      for(int m = 0; m < 12; m++)
         for(int i = 0; i < counts[m]; i++)
           {
            const MqlRates b = months[m].r[i];
            FileWriteString(h, StringFormat("%s,%s,%s,%s,%s,%I64d,%d\n", TimeToString(b.time, TIME_DATE | TIME_SECONDS),
                                            DoubleToString(b.open, digits), DoubleToString(b.high, digits),
                                            DoubleToString(b.low, digits), DoubleToString(b.close, digits),
                                            b.tick_volume, b.spread));
            if(first == 0)
               first = b.time;
            last = b.time;
           }
      FileClose(h);
      FileWriteString(man, StringFormat("%s,%s,%d,%d,%s,%s,%d\n", sym, frame, y, rows,
                                        TimeToString(first, TIME_DATE | TIME_SECONDS),
                                        TimeToString(last, TIME_DATE | TIME_SECONDS), digits));
     }
   return more;
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
         bool found = false;
         int misses = 0;
         for(int y = b.year; y >= a.year; y--)
            if(!ExportYear(sym, FrameOf(frames[f]), frames[f], y, digits, found, misses, man))
               break;
         PrintFormat("EXPORT %s %s done", sym, frames[f]);
        }
     }
   FileClose(man);
   Print("EXPORT complete");
  }
