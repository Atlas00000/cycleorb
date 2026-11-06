//+------------------------------------------------------------------+
//| Setup.mqh — one ORB setup (London or New York): range, filters,    |
//| OCO stop orders, entry window, time exit                           |
//+------------------------------------------------------------------+
#ifndef CORB_SETUP_MQH
#define CORB_SETUP_MQH

#include "Config.mqh"
#include "SessionClock.mqh"
#include "Orders.mqh"
#include "Cycle.mqh"
#include "Features.mqh"
#include "Shadow.mqh"
#include "Policy.mqh"
#include "Guard.mqh"

struct OrbSetup
  {
   string         name;
   ENUM_CORB_ZONE zone;
   long           magic;
   bool           enabled;
   int            rangeStartMin;   // local minutes from midnight
   int            rangeMinutes;
   int            entryEndMin;
   int            exitMin;
   datetime       localDay;        // local date the server times below belong to
   datetime       tRangeStart;     // server time
   datetime       tRangeEnd;
   datetime       tEntryEnd;
   datetime       tExit;
   bool           evaluated;       // range decision made for localDay
   bool           waitLogged;      // "trade session closed" logged for localDay
  };

OrbDecision g_dec; // the current setup-day decision (written to the ledger when InpAosLedger)

//+------------------------------------------------------------------+
bool SetupInit(OrbSetup &s, const string name, const ENUM_CORB_ZONE zone, const long magic,
               const bool enabled, const string rangeStart, const int rangeMinutes,
               const string entryEnd, const string exitAt, string &reason)
  {
   s.name         = name;
   s.zone         = zone;
   s.magic        = magic;
   s.enabled      = enabled;
   s.rangeMinutes = rangeMinutes;
   s.localDay     = 0;
   s.evaluated    = false;
   if(!enabled)
      return true;

   if(!CorbParseHHMM(rangeStart, s.rangeStartMin) || !CorbParseHHMM(entryEnd, s.entryEndMin)
      || !CorbParseHHMM(exitAt, s.exitMin))
     {
      reason = name + ": times must be HH:MM";
      return false;
     }
   if(rangeMinutes < 1)
     {
      reason = name + ": range minutes must be >= 1";
      return false;
     }
   if(s.rangeStartMin + rangeMinutes >= s.entryEndMin)
     {
      reason = name + ": range must end before entry end";
      return false;
     }
   if(s.entryEndMin >= s.exitMin)
     {
      reason = name + ": entry end must be before exit";
      return false;
     }
   return true;
  }

//+------------------------------------------------------------------+
void SetupRollDay(OrbSetup &s, const datetime now)
  {
   const datetime day = ClockDayStart(ClockUtcToLocal(s.zone, ClockServerToUtc(now)));
   if(day == s.localDay)
      return;

   s.localDay    = day;
   s.tRangeStart = ClockLocalToServer(s.zone, day + s.rangeStartMin * 60);
   s.tRangeEnd   = ClockLocalToServer(s.zone, day + (s.rangeStartMin + s.rangeMinutes) * 60);
   s.tEntryEnd   = ClockLocalToServer(s.zone, day + s.entryEndMin * 60);
   s.tExit       = ClockLocalToServer(s.zone, day + s.exitMin * 60);

   const int dow = ClockDayOfWeek(day);
   s.evaluated  = (dow == 0 || dow == 6);
   s.waitLogged = false;
  }

//+------------------------------------------------------------------+
void SetupDecisionSide(const bool isBuy, const bool placed, const string skip, const double lots)
  {
   if(isBuy)
     {
      g_dec.placedBuy = placed;
      g_dec.skipBuy = skip;
      g_dec.lotsBuy = lots;
     }
   else
     {
      g_dec.placedSell = placed;
      g_dec.skipSell = skip;
      g_dec.lotsSell = lots;
     }
  }

void SetupPlaceSide(const OrbSetup &s, const bool isBuy, const double entry, const double sl,
                    const double tp, const double risk, const double market, const double minDist)
  {
   const string side = isBuy ? "BUY" : "SELL";
   const bool roomOk = isBuy ? (entry - market > minDist) : (market - entry > minDist);
   if(!roomOk)
     {
      CorbLog(StringFormat("SKIP %s %s: price already at/through entry", s.name, side));
      SetupDecisionSide(isBuy, false, "price_through", 0.0);
      return;
     }
   // Half-point tolerance: at TargetR = 1 the normalised distances are equal and differ only by float noise
   if(MathAbs(tp - entry) < MathAbs(entry - sl) - _Point / 2.0)
     {
      CorbLog(StringFormat("SKIP %s %s: TP distance below SL distance", s.name, side));
      SetupDecisionSide(isBuy, false, "tp_lt_sl", 0.0);
      return;
     }
   const double lots = OrdersLotForRisk(isBuy, entry, sl, risk);
   GuardOnSide(lots <= 0.0);
   if(lots <= 0.0)
     {
      CorbLog(StringFormat("SKIP %s %s: lot below broker minimum (risk=%.2f)", s.name, side, risk));
      SetupDecisionSide(isBuy, false, "lot_min", 0.0);
      return;
     }
   const bool ok = OrdersPlaceStop(s.magic, isBuy, lots, entry, sl, tp, s.name + " ORB");
   SetupDecisionSide(isBuy, ok, ok ? "" : "place_fail", lots);
  }

void SetupEvaluate(const OrbSetup &s)
  {
   if(OrdersCountPositions(s.magic) + OrdersCountPending(s.magic) > 0
      || OrdersEnteredSince(s.magic, s.tRangeStart))
     {
      CorbLog(StringFormat("SKIP %s: already traded / orders live today", s.name));
      g_dec.reason = "already_traded";
      return;
     }

   MqlRates r[];
   const int n = CopyRates(_Symbol, PERIOD_M1, s.tRangeStart, s.tRangeEnd - 1, r);
   if(n < MathMax(1, s.rangeMinutes / 2))
     {
      CorbLog(StringFormat("SKIP %s: only %d M1 bars in range window", s.name, n));
      g_dec.reason = "missing_bars";
      return;
     }
   double hi = r[0].high;
   double lo = r[0].low;
   long spreadSum = r[0].spread;
   for(int i = 1; i < n; i++)
     {
      hi = MathMax(hi, r[i].high);
      lo = MathMin(lo, r[i].low);
      spreadSum += r[i].spread;
     }
   const double range = hi - lo;
   if(range <= 0.0)
     {
      CorbLog(StringFormat("SKIP %s: zero range", s.name));
      g_dec.reason = "zero_range";
      return;
     }

   double atr[];
   if(CopyBuffer(g_atrHandle, 0, 1, 1, atr) != 1 || atr[0] <= 0.0)
     {
      CorbLog(StringFormat("SKIP %s: daily ATR unavailable", s.name));
      g_dec.reason = "warmup";
      return;
     }

   const double ask     = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   const double bid     = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   // Range-window average, not the live tick: range end often lands on a data-release spread spike
   const double spread  = (spreadSum > 0) ? (double)spreadSum / n * _Point : ask - bid;
   const double atrPct  = 100.0 * range / atr[0];
   const double costPct = 100.0 * (spread + InpCommissionPoints * _Point) / range;

   const string info = StringFormat("%s %s hi=%s lo=%s range=%.0fpt atr%%=%.1f spread=%.1fpt (live %.0fpt) cost%%=%.1f",
                                    s.name, TimeToString(s.tRangeStart, TIME_DATE|TIME_MINUTES),
                                    DoubleToString(hi, _Digits), DoubleToString(lo, _Digits),
                                    range / _Point, atrPct, spread / _Point, (ask - bid) / _Point, costPct);
   g_dec.hasRange = true;
   g_dec.hi = hi;
   g_dec.lo = lo;
   g_dec.atr = atr[0];
   g_dec.spreadAvgPt = spread / _Point;
   g_dec.spreadLivePt = (ask - bid) / _Point;
   g_dec.atrPct = atrPct;
   g_dec.costPct = costPct;

   if(atrPct < InpMinRangeATRPct || atrPct > InpMaxRangeATRPct)
     {
      CorbLog("SKIP " + info + " (range/ATR outside band)");
      g_dec.reason = atrPct < InpMinRangeATRPct ? "atr_band_low" : "atr_band_high";
      return;
     }
   if(costPct > InpMaxCostRangePct)
     {
      CorbLog("SKIP " + info + " (cost too high vs range)");
      g_dec.reason = "cost_cap";
      return;
     }
   if(InpMinVolPct > 0.0)
     {
      double volPct = 0.0;
      if(!SetupVolPercentile(volPct))
        {
         CorbLog("SKIP " + info + " (H1 vol percentile unavailable)");
         g_dec.reason = "warmup";
         return;
        }
      g_dec.volPct = volPct;
      if(volPct < InpMinVolPct)
        {
         CorbLog(StringFormat("SKIP %s volpct=%.1f (H1 vol below regime floor)", info, volPct));
         g_dec.reason = "vol_floor";
         return;
        }
     }
   int trendSide = 0;
   if(InpTrendSideOnly)
     {
      if(!SetupTrendSide(trendSide))
        {
         CorbLog("SKIP " + info + " (D1 trend unavailable)");
         g_dec.reason = "warmup";
         return;
        }
      g_dec.trend = trendSide;
      if(trendSide == 0)
        {
         CorbLog("SKIP " + info + " (D1 close on its SMA, no trend side)");
         g_dec.reason = "trend_flat";
         return;
        }
     }

   const double buffer    = MathMax(InpBufferSpreadMult * spread, range * InpBufferRangePct / 100.0);
   const double mid       = (hi + lo) / 2.0;
   const double buyEntry  = OrdersNormalizePrice(hi + buffer);
   const double sellEntry = OrdersNormalizePrice(lo - buffer);
   const double buySL     = OrdersNormalizePrice(InpStopMode == CORB_STOP_MID ? mid : lo);
   const double sellSL    = OrdersNormalizePrice(InpStopMode == CORB_STOP_MID ? mid : hi);
   const double buyTP     = OrdersNormalizePrice(buyEntry + InpTargetR * (buyEntry - buySL));
   const double sellTP    = OrdersNormalizePrice(sellEntry - InpTargetR * (sellSL - sellEntry));
   const double risk      = CycleRiskMoney();
   const double minDist   = (double)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL) * _Point;

   CorbLog(StringFormat("RANGE %s buffer=%.0fpt risk=%.2f trend=%d", info, buffer / _Point, risk, trendSide));
   g_dec.decision = "ARMED";
   g_dec.risk = risk;
   g_dec.buyEntry = buyEntry;
   g_dec.buySL = buySL;
   g_dec.buyTP = buyTP;
   g_dec.sellEntry = sellEntry;
   g_dec.sellSL = sellSL;
   g_dec.sellTP = sellTP;
   g_dec.armBuy = !InpTrendSideOnly || trendSide > 0;
   g_dec.armSell = !InpTrendSideOnly || trendSide < 0;

   // AI OS: L2 policy (permit / withhold / resize) x L4 lifecycle size x L3 drawdown halving; L4 risk cap while compressing.
   // Defaults leave the engine's risk unchanged.
   const AosPolicy pol = PolicyDecide(g_dec);
   string note = pol.note;
   double mult = pol.mult;
   if(HealthSizeMult() < 1.0)
     {
      mult *= HealthSizeMult();
      note += (StringLen(note) > 0 ? " " : "") + (g_hState == "Below frontier" ? "health_below" : "health_near");
     }
   if(GuardSizeMult() < 1.0)
     {
      mult *= GuardSizeMult();
      note += (StringLen(note) > 0 ? " " : "") + "dd_halve";
     }
   double sideRisk = risk;
   if(InpAosCompressRiskPct > 0.0 && HealthCompressingOrWorse() && risk > g_cycle.capital * InpAosCompressRiskPct / 100.0)
     {
      sideRisk = g_cycle.capital * InpAosCompressRiskPct / 100.0;
      note += (StringLen(note) > 0 ? " " : "") + "compress_cap";
     }
   g_dec.aosMult = risk > 0.0 ? mult * sideRisk / risk : mult;
   g_dec.aosNote = note;
   g_dec.healthState = g_hState;
   if(StringLen(note) > 0)
      CorbLog(StringFormat("AOS %s: %s (size x%.2f)", s.name, note, g_dec.aosMult));
   if(g_dec.armBuy)
     {
      if(pol.allowBuy && mult > 0.0)
         SetupPlaceSide(s, true, buyEntry, buySL, buyTP, sideRisk * mult, ask, minDist);
      else
         SetupDecisionSide(true, false, "aos_withhold", 0.0);
     }
   if(g_dec.armSell)
     {
      if(pol.allowSell && mult > 0.0)
         SetupPlaceSide(s, false, sellEntry, sellSL, sellTP, sideRisk * mult, bid, minDist);
      else
         SetupDecisionSide(false, false, "aos_withhold", 0.0);
     }
  }

void SetupDecisionStart(const OrbSetup &s, const string reason)
  {
   DecisionBegin(g_dec, s.name, s.magic, s.localDay, s.tRangeStart, s.tRangeEnd, s.tEntryEnd, s.tExit);
   g_dec.reason = reason;
  }

void SetupDecisionWrite()
  {
   if(!InpAosLedger)
      return;
   LedgerWriteDecision(g_dec);
   ShadowStart(g_dec);
  }

//+------------------------------------------------------------------+
void SetupTick(OrbSetup &s, const datetime now, const bool cycleAllows, const string cycleReason)
  {
   if(!s.enabled)
      return;
   SetupRollDay(s, now);

   const int positions = OrdersCountPositions(s.magic);
   const int pending   = OrdersCountPending(s.magic);

   if(positions > 0 && (now >= s.tExit + 300 || OrdersOldestOpenTime(s.magic) < s.tRangeStart))
      GuardOnCalendarLeak(StringFormat("%s position still open after its exit (%s)", s.name,
                                       TimeToString(s.tExit, TIME_DATE | TIME_MINUTES)));
   if(now >= s.tExit || (now < s.tRangeStart && positions > 0))
     {
      if(positions + pending > 0)
         OrdersFlatten(s.magic, s.name + " time exit");
      return;
     }

   if(pending > 0)
     {
      if(now >= s.tEntryEnd)
         OrdersDeletePending(s.magic, s.name + " entry window closed");
      else if(positions > 0)
         OrdersDeletePending(s.magic, s.name + " OCO");
      else if(!cycleAllows)
         OrdersDeletePending(s.magic, cycleReason);
      else if(PolicyCancelPending(now, s.tRangeEnd, s.tEntryEnd))
         OrdersDeletePending(s.magic, s.name + " AOS pre-release cancel");
     }

   if(s.evaluated || now < s.tRangeEnd || now >= s.tEntryEnd)
      return;
   // Exchange holiday / early close: the CFD can stop trading before tExit and the time exit then cannot close
   if(CorbIsSkipDate(s.localDay))
     {
      s.evaluated = true;
      CorbLog(StringFormat("SKIP %s %s: skip date (holiday / early close)", s.name, TimeToString(s.localDay, TIME_DATE)));
      SetupDecisionStart(s, "skip_date");
      SetupDecisionWrite();
      return;
     }
   // Broker session tables can lag quotes (e.g. US shares on fixed winter hours during US DST): wait, don't lose the day
   if(!ClockTradeSessionOpen(now))
     {
      if(!s.waitLogged)
         CorbLog(StringFormat("WAIT %s: trade session closed at range end, placing when it opens (until entry end)", s.name));
      s.waitLogged = true;
      return;
     }
   s.evaluated = true;

   if(!cycleAllows)
     {
      CorbLog(StringFormat("SKIP %s: %s", s.name, cycleReason));
      SetupDecisionStart(s, StringFind(cycleReason, "last trading day") >= 0 ? "last_day"
                         : (StringFind(cycleReason, "GUARD") == 0 ? "guard" : "cycle"));
      SetupDecisionWrite();
      return;
     }
   SetupDecisionStart(s, "");
   SetupEvaluate(s);
   SetupDecisionWrite();
  }

#endif // CORB_SETUP_MQH
