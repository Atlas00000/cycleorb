//+------------------------------------------------------------------+
//| Cycle.mqh — monthly capital cycle: budget, halt, flatten, ratchet  |
//| Equity here = cycle capital + this EA's realized + floating P&L,   |
//| never whole-account equity.                                        |
//+------------------------------------------------------------------+
#ifndef CORB_CYCLE_MQH
#define CORB_CYCLE_MQH

#include "Config.mqh"

enum ENUM_CORB_CYCLE_STATE
  {
   CORB_CYCLE_ACTIVE  = 0, // Trading allowed
   CORB_CYCLE_HALTED  = 1, // Soft halt: no new entries this month
   CORB_CYCLE_STOPPED = 2  // Flattened: done for this month
  };

struct CycleState
  {
   datetime              start;
   int                   yyyymm;
   double                capital;
   double                realized;
   double                floating;
   int                   openCount;
   double                peakProfitPct;
   ENUM_CORB_CYCLE_STATE state;
   string                reason;
  };

CycleState g_cycle;

//+------------------------------------------------------------------+
int CycleKey(const datetime t)
  {
   MqlDateTime s;
   TimeToStruct(t, s);
   return s.year * 100 + s.mon;
  }

datetime CycleMonthStart(const datetime t)
  {
   MqlDateTime s;
   TimeToStruct(t, s);
   s.day = 1;
   s.hour = 0;
   s.min = 0;
   s.sec = 0;
   return StructToTime(s);
  }

string CycleStateName(const ENUM_CORB_CYCLE_STATE st)
  {
   if(st == CORB_CYCLE_ACTIVE)
      return "ACTIVE";
   if(st == CORB_CYCLE_HALTED)
      return "HALTED";
   return "STOPPED";
  }

//+------------------------------------------------------------------+
double CycleCalcRealized(const datetime from)
  {
   double sum = 0.0;
   if(!HistorySelect(from, TimeCurrent() + 60))
      return 0.0;
   const int n = HistoryDealsTotal();
   for(int i = 0; i < n; i++)
     {
      const ulong deal = HistoryDealGetTicket(i);
      if(deal == 0)
         continue;
      if(HistoryDealGetString(deal, DEAL_SYMBOL) != _Symbol)
         continue;
      if(!CorbIsOurMagic(HistoryDealGetInteger(deal, DEAL_MAGIC)))
         continue;
      sum += HistoryDealGetDouble(deal, DEAL_PROFIT)
             + HistoryDealGetDouble(deal, DEAL_SWAP)
             + HistoryDealGetDouble(deal, DEAL_COMMISSION);
     }
   return sum;
  }

double CycleCalcFloating(int &count)
  {
   double sum = 0.0;
   count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      const ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      if(!CorbIsOurMagic(PositionGetInteger(POSITION_MAGIC)))
         continue;
      sum += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
      count++;
     }
   return sum;
  }

//+------------------------------------------------------------------+
double CycleEquity()
  {
   return g_cycle.capital + g_cycle.realized + g_cycle.floating;
  }

double CycleProfitPct()
  {
   if(g_cycle.capital <= 0.0)
      return 0.0;
   return 100.0 * (CycleEquity() - g_cycle.capital) / g_cycle.capital;
  }

//+------------------------------------------------------------------+
// Live only: survive restarts mid-month (tester runs start clean).
// Terminal globals are shared by every chart, so the name carries the symbol as well as the magic base.
string CycleGVName(const string key)
  {
   return StringFormat("CORB_%s_%s_%d_%s", IntegerToString(InpMagicBase), _Symbol, g_cycle.yyyymm, key);
  }

void CycleSave()
  {
   if(MQLInfoInteger(MQL_TESTER))
      return;
   GlobalVariableSet(CycleGVName("peak"), g_cycle.peakProfitPct);
   GlobalVariableSet(CycleGVName("stopped"), g_cycle.state == CORB_CYCLE_STOPPED ? 1.0 : 0.0);
  }

void CycleLoad()
  {
   if(MQLInfoInteger(MQL_TESTER))
      return;
   if(GlobalVariableCheck(CycleGVName("peak")))
      g_cycle.peakProfitPct = MathMax(g_cycle.peakProfitPct, GlobalVariableGet(CycleGVName("peak")));
   if(GlobalVariableCheck(CycleGVName("stopped")) && GlobalVariableGet(CycleGVName("stopped")) > 0.5)
     {
      g_cycle.state = CORB_CYCLE_STOPPED;
      g_cycle.reason = "stopped earlier this month (restored)";
     }
  }

//+------------------------------------------------------------------+
void CycleLogSummary(const string tag)
  {
   CorbLog(StringFormat("%s %d capital=%.2f realized=%.2f floating=%.2f pnl=%.2f%% peak=%.2f%% state=%s %s",
                        tag, g_cycle.yyyymm, g_cycle.capital, g_cycle.realized, g_cycle.floating,
                        CycleProfitPct(), g_cycle.peakProfitPct,
                        CycleStateName(g_cycle.state), g_cycle.reason));
  }

void CycleBegin(const datetime now)
  {
   g_cycle.start         = CycleMonthStart(now);
   g_cycle.yyyymm        = CycleKey(now);
   g_cycle.realized      = CycleCalcRealized(g_cycle.start);
   g_cycle.floating      = CycleCalcFloating(g_cycle.openCount);
   g_cycle.capital       = (InpCycleCapital > 0.0)
                           ? InpCycleCapital
                           : AccountInfoDouble(ACCOUNT_BALANCE) - g_cycle.realized;
   g_cycle.peakProfitPct = MathMax(0.0, CycleProfitPct());
   g_cycle.state         = CORB_CYCLE_ACTIVE;
   g_cycle.reason        = "";
   CycleLoad();
   CycleLogSummary("CYCLE_BEGIN");
  }

void CycleOnDeal()
  {
   g_cycle.realized = CycleCalcRealized(g_cycle.start);
  }

//+------------------------------------------------------------------+
void CycleStop(const string why)
  {
   g_cycle.state = CORB_CYCLE_STOPPED;
   g_cycle.reason = why;
   CycleSave();
   CycleLogSummary("CYCLE_STOP");
  }

// Returns true if a new month started on this call.
bool CycleUpdate(const datetime now)
  {
   bool rolled = false;
   if(CycleKey(now) != g_cycle.yyyymm)
     {
      CycleLogSummary("CYCLE_END");
      CycleBegin(now);
      rolled = true;
     }

   // A position that closed since the last tick moved P&L from floating to realized;
   // refresh realized now or equity is misread (OnTradeTransaction may arrive after this tick).
   const int prevOpen = g_cycle.openCount;
   g_cycle.floating = CycleCalcFloating(g_cycle.openCount);
   if(g_cycle.openCount != prevOpen)
      g_cycle.realized = CycleCalcRealized(g_cycle.start);
   if(g_cycle.state == CORB_CYCLE_STOPPED)
      return rolled;

   const double pct = CycleProfitPct();
   if(pct > g_cycle.peakProfitPct)
     {
      g_cycle.peakProfitPct = pct;
      CycleSave();
     }

   if(-pct >= InpHardFlattenPct)
     {
      CycleStop(StringFormat("hard flatten dd=%.2f%%", -pct));
      return rolled;
     }

   if(g_cycle.peakProfitPct >= InpRatchetArmPct)
     {
      const double floorPct = MathMax(InpRatchetFloorPct, g_cycle.peakProfitPct * InpRatchetTrail);
      if(pct <= floorPct)
        {
         CycleStop(StringFormat("ratchet floor %.2f%% hit (pnl %.2f%%, peak %.2f%%)",
                                floorPct, pct, g_cycle.peakProfitPct));
         return rolled;
        }
     }

   if(g_cycle.state == CORB_CYCLE_ACTIVE && -pct >= InpSoftHaltPct)
     {
      g_cycle.state = CORB_CYCLE_HALTED;
      g_cycle.reason = StringFormat("soft halt dd=%.2f%%", -pct);
      CycleLogSummary("CYCLE_HALT");
     }
   return rolled;
  }

//+------------------------------------------------------------------+
bool CycleIsLastTradingDay(const datetime now)
  {
   datetime next = now - (now % 86400) + 86400;
   MqlDateTime s;
   TimeToStruct(next, s);
   while(s.day_of_week == 0 || s.day_of_week == 6)
     {
      next += 86400;
      TimeToStruct(next, s);
     }
   return CycleKey(next) != CycleKey(now);
  }

bool CycleAllowsEntry(const datetime now, string &reason)
  {
   reason = "";
   if(g_cycle.state != CORB_CYCLE_ACTIVE)
     {
      reason = "cycle " + CycleStateName(g_cycle.state) + " " + g_cycle.reason;
      return false;
     }
   if(InpNoEntryLastDay && CycleIsLastTradingDay(now))
     {
      reason = "last trading day of month";
      return false;
     }
   return true;
  }

// Remaining budget down to the hard-flatten level, split across N trades, capped.
double CycleRiskMoney()
  {
   const double floorEquity = g_cycle.capital * (1.0 - InpHardFlattenPct / 100.0);
   double risk = (CycleEquity() - floorEquity) / InpRiskDivisor;
   const double cap = g_cycle.capital * InpMaxRiskPct / 100.0;
   if(risk > cap)
      risk = cap;
   return MathMax(0.0, risk);
  }

#endif // CORB_CYCLE_MQH
