//+------------------------------------------------------------------+
//| CycleORB.mq5 — opening range breakout (London / New York / Tokyo)  |
//| inside a monthly capital cycle (soft halt, hard flatten, ratchet)  |
//+------------------------------------------------------------------+
#property copyright "CycleORB"
#property version   "1.13"
#define CORB_VERSION "1.13"

#include "Include/Config.mqh"
#include "Include/SessionClock.mqh"
#include "Include/Orders.mqh"
#include "Include/Cycle.mqh"
#include "Include/Setup.mqh"

OrbSetup g_setups[3];

//+------------------------------------------------------------------+
void FlattenAll(const string why)
  {
   for(int i = 0; i < ArraySize(g_setups); i++)
      if(OrdersCountPositions(g_setups[i].magic) + OrdersCountPending(g_setups[i].magic) > 0)
         OrdersFlatten(g_setups[i].magic, why);
  }

void UpdateComment()
  {
   if(!MQLInfoInteger(MQL_VISUAL_MODE) && MQLInfoInteger(MQL_TESTER))
      return;
   Comment(StringFormat("CycleORB %d | %s %s\ncapital=%.2f equity=%.2f pnl=%.2f%% peak=%.2f%% | next risk=%.2f",
                        g_cycle.yyyymm, CycleStateName(g_cycle.state), g_cycle.reason,
                        g_cycle.capital, CycleEquity(), CycleProfitPct(), g_cycle.peakProfitPct,
                        CycleRiskMoney()));
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   string reason = "";
   if(!ConfigValidate(reason))
     {
      CorbLog("Init refused: " + reason);
      return INIT_PARAMETERS_INCORRECT;
     }
   if((ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE) != ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
     {
      CorbLog("Init refused: hedging account required (London and New York positions can overlap)");
      return INIT_FAILED;
     }
   if(StringFind(_Symbol, "EURUSD") < 0)
      CorbLog("WARNING built and defaulted for EURUSD, running on " + _Symbol);

   if(!SetupInit(g_setups[0], "LON", CORB_ZONE_LONDON, CorbMagicLondon(), InpLonEnable,
                 InpLonRangeStart, InpLonRangeMinutes, InpLonEntryEnd, InpLonExit, reason)
      || !SetupInit(g_setups[1], "NY", CORB_ZONE_NEWYORK, CorbMagicNewYork(), InpNYEnable,
                    InpNYRangeStart, InpNYRangeMinutes, InpNYEntryEnd, InpNYExit, reason)
      || !SetupInit(g_setups[2], "TKY", CORB_ZONE_TOKYO, CorbMagicTokyo(), InpTkyEnable,
                    InpTkyRangeStart, InpTkyRangeMinutes, InpTkyEntryEnd, InpTkyExit, reason))
     {
      CorbLog("Init refused: " + reason);
      return INIT_PARAMETERS_INCORRECT;
     }

   g_atrHandle = iATR(_Symbol, PERIOD_D1, InpATRPeriod);
   if(g_atrHandle == INVALID_HANDLE)
     {
      CorbLog("Init refused: iATR handle failed");
      return INIT_FAILED;
     }
   if(InpMinVolPct > 0.0 || InpAosLedger)
     {
      g_volHandle = iATR(_Symbol, PERIOD_H1, InpVolATRPeriod);
      if(g_volHandle == INVALID_HANDLE)
        {
         CorbLog("Init refused: H1 iATR handle failed");
         return INIT_FAILED;
        }
     }
   if(InpTrendSideOnly || InpAosLedger || PolicyUsesTrend())
     {
      g_trendHandle = iMA(_Symbol, PERIOD_D1, InpTrendMAPeriod, 0, MODE_SMA, PRICE_CLOSE);
      if(g_trendHandle == INVALID_HANDLE)
        {
         CorbLog("Init refused: D1 iMA handle failed");
         return INIT_FAILED;
        }
     }

   OrdersInit();
   ClockLogInfo();
   if(InpAosClockRefuse && ClockMismatch())
     {
      CorbLog("Init refused: server clock offset does not match InpServerTZ (InpAosClockRefuse)");
      return INIT_FAILED;
     }
   CycleBegin(TimeCurrent());
   ShadowInit();
   GuardInit();
   if(InpAosLedger || PolicyUsesEvents())
      EventsLoad();
   if(InpAosLedger || PolicyUsesCtx())
      FeaturesInit();
   if(InpAosLedger)
     {
      HealthLoadLedger(LedgerFileName("shadow"));
      LedgerOpen();
     }

   CorbLog(StringFormat("Init OK v%s %s | magics LON=%I64d NY=%I64d TKY=%I64d | stop=%s TP=%.2fR | volpct>=%.1f | trendside=%s(SMA%d) | skip dates=%d | aos ledger=%s | soft=%.0f%% hard=%.0f%% ratchet arm=%.0f%% floor=%.0f%% trail=%.2f",
                        CORB_VERSION, _Symbol, CorbMagicLondon(), CorbMagicNewYork(), CorbMagicTokyo(),
                        EnumToString(InpStopMode), InpTargetR, InpMinVolPct,
                        InpTrendSideOnly ? "on" : "off", InpTrendMAPeriod, ArraySize(g_skipDates),
                        InpAosLedger ? "on" : "off",
                        InpSoftHaltPct, InpHardFlattenPct, InpRatchetArmPct, InpRatchetFloorPct, InpRatchetTrail));
   CorbLog(StringFormat("AOS policy: long gate=%s short gate=%s ctx=%.2fATR | event x%.2f window=%s names=[%s] cancel=%dmin | cell %.1f-%.1f%% x%.2f",
                        EnumToString(InpAosLongGate), EnumToString(InpAosShortGate), InpAosCtxGateATR,
                        InpAosEventSizeMult, EnumToString(InpAosEventWindow), InpAosEventNames, InpAosCancelBeforeMin,
                        InpAosCellAtrMin, InpAosCellAtrMax, InpAosCellMult));
   CorbLog(StringFormat("AOS guards: calendar kill=%s slip abort=%.2fR lot guard=%.0f%% dd limit=%.1f%% clock refuse=%s | health sizing=%s baseE=%+.3fR leak=%.1fpp compress cap=%.1f%%",
                        InpAosCalendarKill ? "on" : "off", InpAosSlipAbortR, InpAosLotGuardPct, InpAosDdLimitPct,
                        InpAosClockRefuse ? "on" : "off", InpAosHealthSizing ? "on" : "off", InpAosHealthBaseE,
                        InpAosHealthLeakPP, InpAosCompressRiskPct));
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   CycleLogSummary("CYCLE_PARTIAL");
   if(InpAosLedger)
     {
      ShadowCloseAll();
      LedgerClose();
     }
   if(g_atrHandle != INVALID_HANDLE)
      IndicatorRelease(g_atrHandle);
   if(g_volHandle != INVALID_HANDLE)
      IndicatorRelease(g_volHandle);
   if(g_trendHandle != INVALID_HANDLE)
      IndicatorRelease(g_trendHandle);
   Comment("");
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   const datetime now = TimeCurrent();

   if(CycleUpdate(now))
     {
      FlattenAll("new month");
      if(InpAosLedger)
         HealthEvaluate();
     }
   if(g_cycle.state == CORB_CYCLE_STOPPED)
      FlattenAll("cycle stopped");

   if(InpAosLedger)
      ShadowTick(now);

   string reason = "";
   const bool allow = CycleAllowsEntry(now, reason) && GuardAllowsEntry(reason);
   for(int i = 0; i < ArraySize(g_setups); i++)
      SetupTick(g_setups[i], now, allow, reason);

   UpdateComment();
  }

void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest &request,
                        const MqlTradeResult &result)
  {
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD || trans.symbol != _Symbol)
      return;
   if(trans.deal == 0 || !HistoryDealSelect(trans.deal))
      return;
   const long magic = HistoryDealGetInteger(trans.deal, DEAL_MAGIC);
   if(!CorbIsOurMagic(magic))
      return;

   const bool isIn = HistoryDealGetInteger(trans.deal, DEAL_ENTRY) == DEAL_ENTRY_IN;
   const double money = HistoryDealGetDouble(trans.deal, DEAL_PROFIT) + HistoryDealGetDouble(trans.deal, DEAL_SWAP)
                        + HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);
   const ulong position = (ulong)HistoryDealGetInteger(trans.deal, DEAL_POSITION_ID);
   const bool isBuy = HistoryDealGetInteger(trans.deal, DEAL_TYPE) == DEAL_TYPE_BUY;
   const double fill = HistoryDealGetDouble(trans.deal, DEAL_PRICE);
   const ulong order = (ulong)HistoryDealGetInteger(trans.deal, DEAL_ORDER);

   if(isIn)
      OrdersDeletePending(magic, "OCO fill");
   CycleOnDeal();
   GuardOnDealMoney(money);

   // L3 entry-slippage abort: close at market, no re-entry today (the restart guard sees the entry)
   double slipR = 0.0;
   if(isIn && InpAosSlipAbortR > 0.0 && HistoryOrderSelect(order)
      && GuardSlipAbort(isBuy, HistoryOrderGetDouble(order, ORDER_PRICE_OPEN), fill,
                        HistoryOrderGetDouble(order, ORDER_SL), slipR))
     {
      CorbLog(StringFormat("GUARD SLIP_ABORT position #%I64u: entry slippage %.2fR > %.2fR, closing", position, slipR,
                           InpAosSlipAbortR));
      g_trade.PositionClose(position, InpSlippagePoints);
     }

   if(InpAosLedger)
      for(int i = 0; i < ArraySize(g_setups); i++)
         if(g_setups[i].magic == magic)
            LedgerOnDeal(trans.deal, g_setups[i].name, g_setups[i].localDay);
  }
