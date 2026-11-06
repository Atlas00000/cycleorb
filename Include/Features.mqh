//+------------------------------------------------------------------+
//| Features.mqh — decision context at range end and the AI OS L1      |
//| feature row (observe only: nothing here changes trading)           |
//+------------------------------------------------------------------+
#ifndef CORB_FEATURES_MQH
#define CORB_FEATURES_MQH

#include "Config.mqh"
#include "Events.mqh"

int g_atrHandle   = INVALID_HANDLE;
int g_volHandle   = INVALID_HANDLE; // H1 ATR: filter (InpMinVolPct > 0) and/or ledger features
int g_trendHandle = INVALID_HANDLE; // D1 SMA: filter (InpTrendSideOnly) and/or ledger features

// One setup-day decision: filled by SetupEvaluate, written by the ledger, armed by the shadow tracker
struct OrbDecision
  {
   datetime time;
   datetime localDay;
   string   setup;
   long     magic;
   string   decision;      // ARMED / SKIP
   string   reason;
   bool     hasRange;
   double   hi;
   double   lo;
   double   atr;
   double   spreadAvgPt;
   double   spreadLivePt;
   double   atrPct;
   double   costPct;
   double   volPct;        // -1 = not computed by the engine
   int      trend;         // engine trend side (0 when the filter is off)
   datetime tRangeStart;
   datetime tRangeEnd;
   datetime tEntryEnd;
   datetime tExit;
   bool     armBuy;        // side the engine intends to arm (after the trend-side filter)
   bool     armSell;
   bool     placedBuy;
   bool     placedSell;
   string   skipBuy;       // side-level skip: price_through / tp_lt_sl / lot_min
   string   skipSell;
   double   lotsBuy;
   double   lotsSell;
   double   risk;
   double   buyEntry;
   double   buySL;
   double   buyTP;
   double   sellEntry;
   double   sellSL;
   double   sellTP;
   double   aosMult;       // L2 policy size multiplier applied to the engine's risk
   string   aosNote;       // L2 / L3 / L4 reasons (withholds, event day, weak cell, health, DD halving)
   string   healthState;   // L4 lifecycle state at decision time
  };

void DecisionBegin(OrbDecision &d, const string setup, const long magic, const datetime localDay,
                   const datetime tRangeStart, const datetime tRangeEnd, const datetime tEntryEnd, const datetime tExit)
  {
   d.time = TimeCurrent();
   d.localDay = localDay;
   d.setup = setup;
   d.magic = magic;
   d.decision = "SKIP";
   d.reason = "";
   d.hasRange = false;
   d.hi = 0.0;
   d.lo = 0.0;
   d.atr = 0.0;
   d.spreadAvgPt = 0.0;
   d.spreadLivePt = 0.0;
   d.atrPct = 0.0;
   d.costPct = 0.0;
   d.volPct = -1.0;
   d.trend = 0;
   d.tRangeStart = tRangeStart;
   d.tRangeEnd = tRangeEnd;
   d.tEntryEnd = tEntryEnd;
   d.tExit = tExit;
   d.armBuy = false;
   d.armSell = false;
   d.placedBuy = false;
   d.placedSell = false;
   d.skipBuy = "";
   d.skipSell = "";
   d.lotsBuy = 0.0;
   d.lotsSell = 0.0;
   d.risk = 0.0;
   d.buyEntry = 0.0;
   d.buySL = 0.0;
   d.buyTP = 0.0;
   d.sellEntry = 0.0;
   d.sellSL = 0.0;
   d.sellTP = 0.0;
   d.aosMult = 1.0;
   d.aosNote = "";
   d.healthState = "";
  }

string DecisionEventId(const OrbDecision &d)
  {
   string day = TimeToString(d.localDay, TIME_DATE);
   StringReplace(day, ".", "");
   return StringFormat("%I64d-%s", d.magic, day);
  }

//+------------------------------------------------------------------+
// +1 if the previous completed D1 close is above its SMA, -1 below, 0 equal
bool SetupTrendSide(int &side)
  {
   double ma[];
   if(CopyBuffer(g_trendHandle, 0, 1, 1, ma) != 1 || ma[0] <= 0.0)
      return false;
   const double close = iClose(_Symbol, PERIOD_D1, 1);
   if(close <= 0.0)
      return false;
   side = (close > ma[0]) ? 1 : ((close < ma[0]) ? -1 : 0);
   return true;
  }

// Share (0-100) of the last InpVolLookback completed H1 ATR values that are <= the latest one
bool SetupVolPercentile(double &pct)
  {
   double v[];
   if(CopyBuffer(g_volHandle, 0, 1, InpVolLookback, v) != InpVolLookback)
      return false;
   const double last = v[InpVolLookback - 1];
   int below = 0;
   for(int i = 0; i < InpVolLookback; i++)
      if(v[i] <= last)
         below++;
   pct = 100.0 * below / InpVolLookback;
   return true;
  }

//+------------------------------------------------------------------+
string FeatNum(const double v, const int digits, const bool ok = true)
  {
   return ok ? DoubleToString(v, digits) : "";
  }

string FeatBool(const bool v)
  {
   return v ? "1" : "0";
  }

bool FeatOpen(const string sym, const datetime t, double &open)
  {
   MqlRates r[];
   if(CopyRates(sym, PERIOD_M1, t, 1, r) != 1)
      return false;
   open = r[0].open;
   return true;
  }

// Close of the M5 bar that ends at or before t (only completed data)
bool FeatCloseBefore(const string sym, const datetime t, double &close)
  {
   MqlRates r[];
   if(CopyRates(sym, PERIOD_M5, t - 1, 1, r) != 1)
      return false;
   close = r[0].close;
   return true;
  }

// Previous completed D1 bars' average true range (14) and last close-to-close move
bool FeatDailyMove(const string sym, double &atr, double &move)
  {
   MqlRates r[];
   if(CopyRates(sym, PERIOD_D1, 1, 15, r) != 15)
      return false;
   double sum = 0.0;
   for(int i = 1; i < 15; i++)
      sum += MathMax(r[i].high, r[i - 1].close) - MathMin(r[i].low, r[i - 1].close);
   atr = sum / 14.0;
   move = r[14].close - r[13].close;
   return atr > 0.0;
  }

bool FeatIsThirdFriday(const datetime day)
  {
   MqlDateTime s;
   TimeToStruct(day, s);
   return s.day_of_week == 5 && s.day >= 15 && s.day <= 21;
  }

string FeaturesHeader()
  {
   string h = "atr_pct,cost_pct,spread_avg_pt,spread_live_pt,vol_pct,trend_side,range_atr,"
              "gap_atr,pre_drift_atr,range_pos_prev,brk_prev_high,brk_prev_low,inside_prev,outside_prev,nr4,nr7,"
              "sma_dist_hi_atr,sma_dist_lo_atr,dow,"
              "ev_tier1_entry,ev_tier1_hold,ev_next_min,ev_first_hold,opex,quad_witching";
   for(int i = 1; i <= 3; i++)
      h += StringFormat(",ctx%d_sym,ctx%d_prevday_atr,ctx%d_lookback_atr", i, i, i);
   return h;
  }

string FeaturesBlank()
  {
   string cols[];
   const int n = StringSplit(FeaturesHeader(), ',', cols);
   string row = "";
   for(int i = 1; i < n; i++)
      row += ",";
   return row;
  }

// All values use data completed at or before the decision time (range end or later)
string FeaturesRow(const OrbDecision &d)
  {
   if(!d.hasRange || d.atr <= 0.0)
      return FeaturesBlank();
   const double atr = d.atr;

   // --- core regime (engine values, computed here when the engine's filter is off)
   double volPct = d.volPct;
   bool volOk = volPct >= 0.0;
   if(!volOk && g_volHandle != INVALID_HANDLE)
      volOk = SetupVolPercentile(volPct);
   int trendSide = 0;
   const bool trendOk = (g_trendHandle != INVALID_HANDLE) && SetupTrendSide(trendSide);
   string row = StringFormat("%.2f,%.2f,%.1f,%.1f,%s,%s,%.4f", d.atrPct, d.costPct, d.spreadAvgPt, d.spreadLivePt,
                             FeatNum(volPct, 1, volOk), trendOk ? IntegerToString(trendSide) : "", d.atrPct / 100.0);

   // --- ORB structure versus the previous completed D1 bars
   MqlRates dd[];
   const bool dOk = CopyRates(_Symbol, PERIOD_D1, 1, 7, dd) == 7;   // dd[6] = previous day, dd[5] = the day before
   double openRs = 0.0, openPre = 0.0;
   const bool oOk = FeatOpen(_Symbol, d.tRangeStart, openRs);
   const bool pOk = oOk && FeatOpen(_Symbol, d.tRangeStart - 3600, openPre);
   double ma[];
   const bool maOk = g_trendHandle != INVALID_HANDLE && CopyBuffer(g_trendHandle, 0, 1, 1, ma) == 1 && ma[0] > 0.0;
   if(dOk)
     {
      const MqlRates p = dd[6];
      const MqlRates q = dd[5];
      const double pr = p.high - p.low;
      bool nr4 = true, nr7 = true;
      for(int i = 0; i < 6; i++)
        {
         const double ri = dd[i].high - dd[i].low;
         if(ri < pr)
           {
            nr7 = false;
            if(i >= 3)
               nr4 = false;
           }
        }
      row += StringFormat(",%s,%s,%s,%s,%s,%s,%s,%s,%s",
                          FeatNum((openRs - p.close) / atr, 3, oOk), FeatNum((openRs - openPre) / atr, 3, pOk),
                          FeatNum(((d.hi + d.lo) / 2.0 - p.low) / MathMax(pr, _Point), 3),
                          FeatBool(d.hi > p.high), FeatBool(d.lo < p.low),
                          FeatBool(p.high <= q.high && p.low >= q.low), FeatBool(p.high > q.high && p.low < q.low),
                          FeatBool(nr4), FeatBool(nr7));
     }
   else
      row += ",,,,,,,,,";
   MqlDateTime ls;
   TimeToStruct(d.localDay, ls);
   row += StringFormat(",%s,%s,%d", FeatNum(maOk ? (d.hi - ma[0]) / atr : 0.0, 3, maOk),
                       FeatNum(maOk ? (d.lo - ma[0]) / atr : 0.0, 3, maOk), ls.day_of_week);

   // --- calendar (high-impact events in the entry window, in the hold, next event)
   if(g_evLoaded)
     {
      string first = EventsFirst(d.tRangeEnd, d.tExit);
      StringReplace(first, ",", ";");
      row += StringFormat(",%d,%d,%d,%s", EventsCount(d.tRangeStart, d.tEntryEnd), EventsCount(d.tRangeEnd, d.tExit),
                          EventsMinutesToNext(d.tRangeEnd, 24 * 60), first);
     }
   else
      row += ",,,,";
   const bool opex = FeatIsThirdFriday(d.localDay);
   row += StringFormat(",%s,%s", FeatBool(opex), FeatBool(opex && ls.mon % 3 == 0));

   // --- cross-session context (other symbols, move into the range start and previous-day move, in their D1 ATR)
   string syms[];
   const int ns = StringSplit(InpAosCtxSymbols, ',', syms);
   for(int i = 0; i < 3; i++)
     {
      if(i >= ns || StringLen(syms[i]) == 0)
        {
         row += ",,,";
         continue;
        }
      string sym = syms[i];
      StringTrimLeft(sym);
      StringTrimRight(sym);
      double catr = 0.0, cmove = 0.0, cNow = 0.0, cThen = 0.0;
      const bool aOk = FeatDailyMove(sym, catr, cmove);
      const bool lOk = aOk && FeatCloseBefore(sym, d.tRangeStart, cNow)
                       && FeatCloseBefore(sym, d.tRangeStart - InpAosCtxHours * 3600, cThen);
      row += StringFormat(",%s,%s,%s", sym, FeatNum(aOk ? cmove / catr : 0.0, 3, aOk),
                          FeatNum(lOk ? (cNow - cThen) / catr : 0.0, 3, lOk));
     }
   return row;
  }

void FeaturesInit()
  {
   string syms[];
   const int ns = StringSplit(InpAosCtxSymbols, ',', syms);
   for(int i = 0; i < ns && i < 3; i++)
     {
      string sym = syms[i];
      StringTrimLeft(sym);
      StringTrimRight(sym);
      if(StringLen(sym) > 0 && !SymbolSelect(sym, true))
         CorbLog("AOS context symbol not available: " + sym);
     }
  }

#endif // CORB_FEATURES_MQH
