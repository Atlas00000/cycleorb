//+------------------------------------------------------------------+
//| Config.mqh — inputs, magic numbers, validation                     |
//+------------------------------------------------------------------+
#ifndef CORB_CONFIG_MQH
#define CORB_CONFIG_MQH

enum ENUM_CORB_SERVER_TZ
  {
   CORB_TZ_GMT2_US_DST = 0, // GMT+2, GMT+3 during US DST (most MT5 brokers)
   CORB_TZ_FIXED       = 1  // Fixed offset (InpServerFixedOffsetH)
  };

enum ENUM_CORB_STOP_MODE
  {
   CORB_STOP_OPPOSITE = 0, // Opposite side of the range
   CORB_STOP_MID      = 1  // Middle of the range
  };

input group "Server time"
input ENUM_CORB_SERVER_TZ InpServerTZ        = CORB_TZ_GMT2_US_DST; // Broker server time convention
input int                 InpServerFixedOffsetH = 2;                // Fixed offset hours (CORB_TZ_FIXED only)

input group "London setup (London local time)"
input bool   InpLonEnable       = true;    // Enable London setup
input string InpLonRangeStart   = "08:00"; // Range start HH:MM
input int    InpLonRangeMinutes = 30;      // Range length (minutes)
input string InpLonEntryEnd     = "11:00"; // Cancel unfilled orders at HH:MM
input string InpLonExit         = "16:00"; // Close everything at HH:MM

input group "New York setup (New York local time)"
input bool   InpNYEnable        = true;    // Enable New York setup
input string InpNYRangeStart    = "08:00"; // Range start HH:MM (try 09:30 too)
input int    InpNYRangeMinutes  = 30;      // Range length (minutes)
input string InpNYEntryEnd      = "11:30"; // Cancel unfilled orders at HH:MM
input string InpNYExit          = "15:00"; // Close everything at HH:MM

input group "Tokyo setup (Tokyo local time, JST = UTC+9, no DST)"
input bool   InpTkyEnable       = false;   // Enable Tokyo setup
input string InpTkyRangeStart   = "09:00"; // Range start HH:MM (TSE cash open)
input int    InpTkyRangeMinutes = 60;      // Range length (minutes)
input string InpTkyEntryEnd     = "11:30"; // Cancel unfilled orders at HH:MM (TSE lunch)
input string InpTkyExit         = "15:25"; // Close everything at HH:MM (TSE close 15:30)

input group "Entry / exit"
input ENUM_CORB_STOP_MODE InpStopMode       = CORB_STOP_OPPOSITE; // Stop placement
input double              InpTargetR        = 2.0;  // Take profit as multiple of risk (R), >= 1
input double              InpBufferSpreadMult = 2.0; // Entry buffer: spread multiple
input double              InpBufferRangePct = 5.0;  // Entry buffer: % of range (larger of the two)

input group "Filters"
input int    InpATRPeriod        = 14;   // Daily ATR period
input double InpMinRangeATRPct   = 10.0; // Min range width, % of daily ATR
input double InpMaxRangeATRPct   = 35.0; // Max range width, % of daily ATR
input double InpMaxCostRangePct  = 10.0; // Max (spread + commission) as % of range
input int    InpCommissionPoints = 0;    // Round-turn commission in points (raw-spread accounts)
input double InpMinVolPct        = 0.0;  // Min H1 ATR percentile at range end, 0-100 (0 = off)
input int    InpVolATRPeriod     = 20;   // H1 ATR period for the volatility percentile
input int    InpVolLookback      = 500;  // H1 bars ranked for the volatility percentile
input bool   InpTrendSideOnly    = false; // Arm only the side of previous D1 close vs D1 SMA (false = both sides)
input int    InpTrendMAPeriod    = 20;   // D1 SMA period for the trend side

input group "Calendar"
input string InpSkipDates        = "";   // No orders on these exchange-local dates (holidays / early closes), YYMMDD or YYYYMMDD, comma-separated

input group "Monthly cycle"
input double InpCycleCapital     = 0.0;  // Fixed allocation per month (0 = balance at month start)
input double InpSoftHaltPct      = 30.0; // Drawdown % that blocks new entries
input double InpHardFlattenPct   = 38.0; // Drawdown % that flattens and stops the month
input double InpRatchetArmPct    = 20.0; // Month profit % that arms the ratchet
input double InpRatchetFloorPct  = 10.0; // Minimum locked profit % once armed
input double InpRatchetTrail     = 0.5;  // Floor = this fraction of peak month profit
input double InpRiskDivisor      = 8.0;  // Risk per trade = remaining budget / this
input double InpMaxRiskPct       = 8.0;  // Cap on risk per trade, % of cycle capital
input bool   InpNoEntryLastDay   = true; // No new entries on last trading day of month

input group "AI OS observe (ledger, shadow, features; never changes trading)"
input bool   InpAosLedger        = false;             // Write decision / event / shadow ledgers to Common\Files\CycleORB
input string InpAosRunTag        = "";                // Tester run tag appended to ledger file names (e.g. P1obs)
input string InpAosEventCcy      = "USD,EUR,GBP,JPY"; // High-impact calendar currencies tagged in the ledger
input string InpAosCtxSymbols    = "";                // Cross-session context symbols, comma-separated (max 3)
input int    InpAosCtxHours      = 8;                 // Context look-back before range start (hours)

enum ENUM_AOS_SIDE_GATE
  {
   AOS_GATE_OFF   = 0, // Off (engine behaviour)
   AOS_GATE_TREND = 1, // Arm only on the D1 trend side (previous close vs SMA)
   AOS_GATE_CTX1  = 2  // Withhold when context symbol 1's previous day moved against the side by > threshold
  };

enum ENUM_AOS_EVENT_WINDOW
  {
   AOS_EV_ENTRY = 0, // Range start to entry end
   AOS_EV_HOLD  = 1  // Range end to exit
  };

input group "AI OS policy L2 (permit / withhold / resize; defaults = engine unchanged)"
input ENUM_AOS_SIDE_GATE    InpAosLongGate        = AOS_GATE_OFF; // Long-side gate
input ENUM_AOS_SIDE_GATE    InpAosShortGate       = AOS_GATE_OFF; // Short-side gate
input double                InpAosCtxGateATR      = 0.5;          // Context gate threshold (context symbol D1 ATR)
input string                InpAosEventNames      = "";           // Policy event filter: name substrings, comma-separated (empty = all high-impact)
input ENUM_AOS_EVENT_WINDOW InpAosEventWindow     = AOS_EV_ENTRY; // Window in which a filtered event marks the day
input double                InpAosEventSizeMult   = 1.0;          // Size multiplier on event days (1 = off, 0 = skip)
input int                   InpAosCancelBeforeMin = 0;            // Cancel pending orders N min before a filtered event in the entry window (0 = off)
input double                InpAosCellAtrMin      = 0.0;          // Range/ATR % cell resized by InpAosCellMult: from
input double                InpAosCellAtrMax      = 0.0;          // ... to (0 = off)
input double                InpAosCellMult        = 1.0;          // Size multiplier inside the cell

input group "AI OS guardrails L3 / health L4 (defaults off)"
input bool   InpAosCalendarKill    = false; // L3: block new entries after a failed exit / overnight hold (live: clear the CORB_..._calkill GV)
input double InpAosSlipAbortR      = 0.0;   // L3: close at market if entry slippage > this many R (0 = off)
input double InpAosLotGuardPct     = 0.0;   // L3: stop the asset if > this % of the last 40 armed sides hit the lot minimum (0 = off)
input double InpAosDdLimitPct      = 0.0;   // L3: asset DD limit %: size x0.5 at 0.8 x limit, restored at 0.5 x (0 = off)
input bool   InpAosClockRefuse     = false; // L3 live: refuse init when the server clock offset does not match InpServerTZ
input bool   InpAosHealthSizing    = false; // L4: lifecycle sizing (Near frontier x0.5, Below frontier x0); needs InpAosLedger
input double InpAosHealthBaseE     = 0.0;   // L4: validation baseline E (R per event) for the Compressing / Expanding lines
input double InpAosHealthLeakPP    = 1.0;   // L4: slippage leak (pp) subtracted from BM
input double InpAosCompressRiskPct = 0.0;   // L4: risk cap (% of cycle capital) while Compressing or worse (0 = off)

input group "Execution"
input long   InpMagicBase        = 26110100; // Magic base (London +1, New York +2, Tokyo +3)
input int    InpSlippagePoints   = 10;       // Max slippage on closes (points)
input double InpMaxLot           = 50.0;     // Hard lot cap per order

//+------------------------------------------------------------------+
long CorbMagicLondon()  { return InpMagicBase + 1; }
long CorbMagicNewYork() { return InpMagicBase + 2; }
long CorbMagicTokyo()   { return InpMagicBase + 3; }

bool CorbIsOurMagic(const long magic)
  {
   return (magic == CorbMagicLondon() || magic == CorbMagicNewYork() || magic == CorbMagicTokyo());
  }

//+------------------------------------------------------------------+
void CorbLog(const string msg)
  {
   Print("[CycleORB] ", msg);
  }

//+------------------------------------------------------------------+
bool CorbParseHHMM(const string s, int &minutes)
  {
   string parts[];
   if(StringSplit(s, ':', parts) != 2)
      return false;
   const int h = (int)StringToInteger(parts[0]);
   const int m = (int)StringToInteger(parts[1]);
   if(h < 0 || h > 23 || m < 0 || m > 59)
      return false;
   minutes = h * 60 + m;
   return true;
  }

//+------------------------------------------------------------------+
datetime g_skipDates[]; // day starts (00:00) of InpSkipDates

// Accepts YYMMDD, YYYYMMDD, YYYY.MM.DD or YYYY-MM-DD, separated by commas, semicolons or spaces.
// MT5 truncates string inputs at 255 characters without an error: use YYMMDD for long lists.
bool ConfigParseSkipDates(string &reason)
  {
   ArrayResize(g_skipDates, 0);
   if(StringLen(InpSkipDates) >= 250)
      CorbLog(StringFormat("WARNING InpSkipDates is %d characters: MT5 truncates inputs at 255, the last dates may be lost (use YYMMDD)",
                           StringLen(InpSkipDates)));
   string list = InpSkipDates;
   StringReplace(list, ";", ",");
   StringReplace(list, " ", ",");
   string parts[];
   const int n = StringSplit(list, ',', parts);
   for(int i = 0; i < n; i++)
     {
      string p = parts[i];
      StringReplace(p, ".", "");
      StringReplace(p, "-", "");
      if(p == "")
         continue;
      if(StringLen(p) == 6)
         p = "20" + p;
      const string ymd = StringSubstr(p, 0, 4) + "." + StringSubstr(p, 4, 2) + "." + StringSubstr(p, 6, 2);
      const datetime d = StringToTime(ymd);
      if(StringLen(p) != 8 || d <= 0 || TimeToString(d, TIME_DATE) != ymd)
        {
         reason = "skip date '" + parts[i] + "' is not a valid YYYYMMDD date";
         return false;
        }
      const int k = ArraySize(g_skipDates);
      ArrayResize(g_skipDates, k + 1);
      g_skipDates[k] = d;
     }
   return true;
  }

bool CorbIsSkipDate(const datetime localDay)
  {
   for(int i = 0; i < ArraySize(g_skipDates); i++)
      if(g_skipDates[i] == localDay)
         return true;
   return false;
  }

//+------------------------------------------------------------------+
bool ConfigValidate(string &reason)
  {
   reason = "";
   if(!InpLonEnable && !InpNYEnable && !InpTkyEnable)
                                                { reason = "all setups disabled"; return false; }
   if(InpServerTZ == CORB_TZ_FIXED && (InpServerFixedOffsetH < -12 || InpServerFixedOffsetH > 14))
                                                { reason = "fixed offset out of range"; return false; }
   if(InpTargetR < 1.0)                         { reason = "TargetR must be >= 1 (never TP < SL)"; return false; }
   if(InpBufferSpreadMult < 0.0 || InpBufferRangePct < 0.0)
                                                { reason = "buffers must be >= 0"; return false; }
   if(InpATRPeriod < 1)                         { reason = "ATR period must be >= 1"; return false; }
   if(InpMinRangeATRPct < 0.0 || InpMaxRangeATRPct <= InpMinRangeATRPct)
                                                { reason = "range ATR band invalid"; return false; }
   if(InpMaxCostRangePct <= 0.0)                { reason = "MaxCostRangePct must be > 0"; return false; }
   if(InpCommissionPoints < 0)                  { reason = "commission must be >= 0"; return false; }
   if(InpMinVolPct < 0.0 || InpMinVolPct >= 100.0)
                                                { reason = "MinVolPct must be in [0,100)"; return false; }
   if(InpVolATRPeriod < 1 || InpVolLookback < 20)
                                                { reason = "vol ATR period >= 1, lookback >= 20"; return false; }
   if(InpTrendMAPeriod < 2)                     { reason = "trend MA period must be >= 2"; return false; }
   if(InpCycleCapital < 0.0)                    { reason = "cycle capital must be >= 0"; return false; }
   if(InpSoftHaltPct <= 0.0 || InpHardFlattenPct <= InpSoftHaltPct || InpHardFlattenPct >= 100.0)
                                                { reason = "need 0 < soft halt < hard flatten < 100"; return false; }
   if(InpRatchetArmPct <= 0.0 || InpRatchetFloorPct < 0.0 || InpRatchetFloorPct >= InpRatchetArmPct)
                                                { reason = "need 0 <= ratchet floor < arm"; return false; }
   if(InpRatchetTrail <= 0.0 || InpRatchetTrail > 1.0)
                                                { reason = "ratchet trail must be in (0,1]"; return false; }
   if(InpRiskDivisor < 1.0)                     { reason = "risk divisor must be >= 1"; return false; }
   if(InpMaxRiskPct <= 0.0)                     { reason = "max risk % must be > 0"; return false; }
   if(InpMagicBase <= 0)                        { reason = "magic base must be > 0"; return false; }
   if(InpMaxLot <= 0.0)                         { reason = "max lot must be > 0"; return false; }
   if(InpAosCtxHours < 1 || InpAosCtxHours > 48) { reason = "AOS context hours must be 1-48"; return false; }
   if(InpAosEventSizeMult < 0.0 || InpAosEventSizeMult > 1.0 || InpAosCellMult < 0.0 || InpAosCellMult > 1.0)
                                                { reason = "AOS size multipliers must be in [0,1] (no sizing up)"; return false; }
   if(InpAosCtxGateATR <= 0.0 || InpAosCancelBeforeMin < 0 || InpAosCellAtrMax < 0.0
      || (InpAosCellAtrMax > 0.0 && InpAosCellAtrMax <= InpAosCellAtrMin))
                                                { reason = "AOS policy thresholds invalid"; return false; }
   if(InpAosHealthSizing && !InpAosLedger)       { reason = "AOS health sizing needs InpAosLedger (shadow stream)"; return false; }
   if(InpAosSlipAbortR < 0.0 || InpAosLotGuardPct < 0.0 || InpAosDdLimitPct < 0.0 || InpAosDdLimitPct >= 100.0
      || InpAosHealthLeakPP < 0.0 || InpAosCompressRiskPct < 0.0)
                                                { reason = "AOS guard / health inputs invalid"; return false; }
   return ConfigParseSkipDates(reason);
  }

#endif // CORB_CONFIG_MQH
