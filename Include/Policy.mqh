//+------------------------------------------------------------------+
//| Policy.mqh — AI OS L2 deterministic policy                         |
//| Permit / withhold a side, or resize the engine's risk. Never moves |
//| range, entry, stop, target or exit. Defaults = engine unchanged.   |
//+------------------------------------------------------------------+
#ifndef CORB_POLICY_MQH
#define CORB_POLICY_MQH

#include "Config.mqh"
#include "Features.mqh"
#include "Events.mqh"

struct AosPolicy
  {
   bool   allowBuy;
   bool   allowSell;
   double mult;
   string note;
  };

bool PolicyUsesEvents()
  {
   return InpAosEventSizeMult != 1.0 || InpAosCancelBeforeMin > 0;
  }

bool PolicyUsesTrend()
  {
   return InpAosLongGate == AOS_GATE_TREND || InpAosShortGate == AOS_GATE_TREND;
  }

bool PolicyUsesCtx()
  {
   return InpAosLongGate == AOS_GATE_CTX1 || InpAosShortGate == AOS_GATE_CTX1;
  }

// High-impact events with from <= time < to whose name contains one of InpAosEventNames (empty = all loaded)
int PolicyEventCount(const datetime from, const datetime to)
  {
   string names[];
   const int nn = StringSplit(InpAosEventNames, ',', names);
   int n = 0;
   for(int i = 0; i < ArraySize(g_evTime); i++)
     {
      if(g_evTime[i] < from || g_evTime[i] >= to)
         continue;
      bool hit = nn == 0;
      for(int k = 0; k < nn && !hit; k++)
         hit = StringLen(names[k]) > 0 && StringFind(g_evName[i], names[k]) >= 0;
      if(hit)
         n++;
     }
   return n;
  }

// side: +1 long, -1 short. Missing data never blocks (fail-open = engine behaviour).
bool PolicyGate(const ENUM_AOS_SIDE_GATE gate, const int side, string &note)
  {
   if(gate == AOS_GATE_TREND)
     {
      int trend = 0;
      if(!SetupTrendSide(trend))
         return true;
      if(trend == side)
         return true;
      note += side > 0 ? "long_vs_trend " : "short_vs_trend ";
      return false;
     }
   if(gate == AOS_GATE_CTX1)
     {
      string syms[];
      if(StringSplit(InpAosCtxSymbols, ',', syms) < 1)
         return true;
      string sym = syms[0];
      StringTrimLeft(sym);
      StringTrimRight(sym);
      double atr = 0.0, move = 0.0;
      if(!FeatDailyMove(sym, atr, move))
         return true;
      if(side * move / atr >= -InpAosCtxGateATR)
         return true;
      note += side > 0 ? "long_vs_ctx1 " : "short_vs_ctx1 ";
      return false;
     }
   return true;
  }

AosPolicy PolicyDecide(const OrbDecision &d)
  {
   AosPolicy p;
   p.note = "";
   p.allowBuy = PolicyGate(InpAosLongGate, +1, p.note);
   p.allowSell = PolicyGate(InpAosShortGate, -1, p.note);
   p.mult = 1.0;
   if(InpAosEventSizeMult != 1.0)
     {
      const datetime from = InpAosEventWindow == AOS_EV_HOLD ? d.tRangeEnd : d.tRangeStart;
      const datetime to = InpAosEventWindow == AOS_EV_HOLD ? d.tExit : d.tEntryEnd;
      if(PolicyEventCount(from, to) > 0)
        {
         p.mult *= InpAosEventSizeMult;
         p.note += "event_day ";
        }
     }
   if(InpAosCellAtrMax > 0.0 && d.atrPct >= InpAosCellAtrMin && d.atrPct < InpAosCellAtrMax)
     {
      p.mult *= InpAosCellMult;
      p.note += "weak_cell ";
     }
   StringTrimRight(p.note);
   return p;
  }

// Pending-order cancel: a filtered event after range end, before entry end, within the next InpAosCancelBeforeMin minutes
bool PolicyCancelPending(const datetime now, const datetime tRangeEnd, const datetime tEntryEnd)
  {
   if(InpAosCancelBeforeMin <= 0)
      return false;
   const datetime from = MathMax(now, tRangeEnd + 60);
   const datetime to = MathMin(now + InpAosCancelBeforeMin * 60, tEntryEnd);
   return from < to && PolicyEventCount(from, to) > 0;
  }

#endif // CORB_POLICY_MQH
