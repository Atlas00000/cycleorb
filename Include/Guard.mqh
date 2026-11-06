//+------------------------------------------------------------------+
//| Guard.mqh — AI OS L3 guardrails (hard, non-AI). Outrank L2 / L4.   |
//| Calendar-leak kill, entry-slippage abort, lot-minimum guard,       |
//| drawdown halving. All off by default.                              |
//+------------------------------------------------------------------+
#ifndef CORB_GUARD_MQH
#define CORB_GUARD_MQH

#include "Config.mqh"

bool   g_gCalKill = false;      // calendar leak seen: no new entries on this symbol until cleared
bool   g_gLotStop = false;      // lot-minimum skips above InpAosLotGuardPct: wrong account size
int    g_gLotRing[40];
int    g_gLotN = 0;
int    g_gLotPos = 0;
double g_gEquity = 0.0;         // own equity: start balance + this EA's closed P&L on this symbol
double g_gPeak = 0.0;
bool   g_gDdHalf = false;

string GuardGVName()
  {
   return StringFormat("CORB_%s_%s_calkill", IntegerToString(InpMagicBase), _Symbol);
  }

void GuardInit()
  {
   g_gEquity = AccountInfoDouble(ACCOUNT_BALANCE);
   g_gPeak = g_gEquity;
   g_gLotN = 0;
   g_gLotPos = 0;
   if(!MQLInfoInteger(MQL_TESTER) && InpAosCalendarKill && GlobalVariableCheck(GuardGVName())
      && GlobalVariableGet(GuardGVName()) > 0.5)
     {
      g_gCalKill = true;
      CorbLog("GUARD CALENDAR_LEAK kill restored: delete global variable " + GuardGVName() + " to clear");
     }
  }

bool GuardAllowsEntry(string &reason)
  {
   if(g_gCalKill)
     {
      reason = "GUARD calendar leak (failed exit / overnight hold)";
      return false;
     }
   if(g_gLotStop)
     {
      reason = "GUARD lot-minimum skips above limit (account too small)";
      return false;
     }
   return true;
  }

double GuardSizeMult()
  {
   return g_gDdHalf ? 0.5 : 1.0;
  }

// Calendar leak: a close refused because the market is closed, a position still open after its exit time,
// or a position carried into a later day. Blocks new entries on this symbol until cleared.
void GuardOnCalendarLeak(const string what)
  {
   if(!InpAosCalendarKill || g_gCalKill)
      return;
   g_gCalKill = true;
   if(!MQLInfoInteger(MQL_TESTER))
      GlobalVariableSet(GuardGVName(), 1.0);
   CorbLog("GUARD CALENDAR_LEAK " + what + ": new entries blocked until cleared");
  }

// One armed side: true = skipped below the broker minimum lot, false = placed
void GuardOnSide(const bool lotMin)
  {
   if(InpAosLotGuardPct <= 0.0)
      return;
   g_gLotRing[g_gLotPos] = lotMin ? 1 : 0;
   g_gLotPos = (g_gLotPos + 1) % 40;
   g_gLotN = MathMin(g_gLotN + 1, 40);
   if(g_gLotN < 20 || g_gLotStop)
      return;
   int skips = 0;
   for(int i = 0; i < g_gLotN; i++)
      skips += g_gLotRing[i];
   const double pct = 100.0 * skips / g_gLotN;
   if(pct > InpAosLotGuardPct)
     {
      g_gLotStop = true;
      CorbLog(StringFormat("GUARD LOT_MIN %.0f%% of the last %d armed sides below the minimum lot (> %.0f%%): asset stopped",
                           pct, g_gLotN, InpAosLotGuardPct));
     }
  }

// Every closed deal of this EA: own equity, drawdown halving at 0.8 x limit, restore below 0.5 x limit
void GuardOnDealMoney(const double money)
  {
   g_gEquity += money;
   g_gPeak = MathMax(g_gPeak, g_gEquity);
   if(InpAosDdLimitPct <= 0.0 || g_gPeak <= 0.0)
      return;
   const double dd = 100.0 * (1.0 - g_gEquity / g_gPeak);
   if(!g_gDdHalf && dd >= 0.8 * InpAosDdLimitPct)
     {
      g_gDdHalf = true;
      CorbLog(StringFormat("GUARD DD %.1f%% >= 0.8 x %.1f%%: size halved", dd, InpAosDdLimitPct));
     }
   else if(g_gDdHalf && dd <= 0.5 * InpAosDdLimitPct)
     {
      g_gDdHalf = false;
      CorbLog(StringFormat("GUARD DD %.1f%% <= 0.5 x %.1f%%: size restored", dd, InpAosDdLimitPct));
     }
  }

// Entry slippage in R of the planned stop distance; true = abort (close at market, no re-entry today)
bool GuardSlipAbort(const bool isBuy, const double requested, const double fill, const double sl, double &slipR)
  {
   slipR = 0.0;
   const double riskPx = MathAbs(requested - sl);
   if(InpAosSlipAbortR <= 0.0 || riskPx <= 0.0)
      return false;
   slipR = (isBuy ? fill - requested : requested - fill) / riskPx;
   return slipR > InpAosSlipAbortR;
  }

#endif // CORB_GUARD_MQH
