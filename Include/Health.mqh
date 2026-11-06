//+------------------------------------------------------------------+
//| Health.mqh — AI OS L4 edge-health observer (edge_framework.md §6.1)|
//| Feeds on the shadow stream (every armed day the engine would have  |
//| traded), so a de-risked or halted asset keeps being measured and   |
//| can recover. Evaluated at each month end; W40 decides, W80 confirms|
//+------------------------------------------------------------------+
#ifndef CORB_HEALTH_MQH
#define CORB_HEALTH_MQH

#include "Config.mqh"

double g_hR[];
string g_hState = "n/a";
double g_hMult = 1.0;

void HealthAdd(const double r)
  {
   const int k = ArraySize(g_hR);
   ArrayResize(g_hR, k + 1);
   g_hR[k] = r;
  }

// EF (BM - leak) and E over g_hR[from, to); false if no wins or no losses
bool HealthWindow(const int from, const int to, double &ef, double &e)
  {
   int wins = 0, losses = 0;
   double sw = 0.0, sl = 0.0, sum = 0.0;
   for(int i = from; i < to; i++)
     {
      sum += g_hR[i];
      if(g_hR[i] > 0.0)
        {
         wins++;
         sw += g_hR[i];
        }
      else if(g_hR[i] < 0.0)
        {
         losses++;
         sl -= g_hR[i];
        }
     }
   e = (to > from) ? sum / (to - from) : 0.0;
   if(wins == 0 || losses == 0)
      return false;
   const double r = (sw / wins) / (sl / losses);
   const double wr = (double)wins / (wins + losses);
   ef = wr - 1.0 / (1.0 + r) - InpAosHealthLeakPP / 100.0;
   return true;
  }

bool HealthCompressingOrWorse()
  {
   return g_hState == "Compressing" || g_hState == "Near frontier" || g_hState == "Below frontier";
  }

double HealthSizeMult()
  {
   return InpAosHealthSizing ? g_hMult : 1.0;
  }

void HealthEvaluate()
  {
   const int n = ArraySize(g_hR);
   double ef40 = 0.0, e40 = 0.0, ef80 = 0.0, e80 = 0.0, efPrev = 0.0, ePrev = 0.0;
   if(n < 40 || !HealthWindow(n - 40, n, ef40, e40))
     {
      g_hState = "n/a";
      g_hMult = 1.0;
      return;
     }
   const bool has80 = n >= 80 && HealthWindow(n - 80, n, ef80, e80);
   const bool hasPrev = n >= 80 && HealthWindow(n - 80, n - 40, efPrev, ePrev);
   const double dD = hasPrev ? ef40 - efPrev : 0.0;
   if(ef40 <= 0.0 && (!has80 || ef80 <= 0.0))
      g_hState = "Below frontier";
   else if(ef40 <= 0.0)
      g_hState = "Near frontier";
   else if(e40 <= InpAosHealthBaseE - 0.10 || (hasPrev && dD <= -0.05))
      g_hState = "Compressing";
   else if(e40 >= InpAosHealthBaseE + 0.10)
      g_hState = "Expanding";
   else
      g_hState = "Stable";
   g_hMult = g_hState == "Below frontier" ? 0.0 : (g_hState == "Near frontier" ? 0.5 : 1.0);
   CorbLog(StringFormat("HEALTH %s n=%d EF40=%+.1fpp E40=%+.3fR EF80=%s dD=%s size x%.1f%s", g_hState, n, 100 * ef40, e40,
                        has80 ? StringFormat("%+.1fpp", 100 * ef80) : "-",
                        hasPrev ? StringFormat("%+.1fpp", 100 * dD) : "-", g_hMult,
                        InpAosHealthSizing ? "" : " (sizing off)"));
  }

// Live restarts: rebuild the stream from this chart's shadow ledger (the tester starts clean)
void HealthLoadLedger(const string shadowFile)
  {
   ArrayResize(g_hR, 0);
   if(MQLInfoInteger(MQL_TESTER))
      return;
   const int h = FileOpen(shadowFile, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE)
      return;
   while(!FileIsEnding(h))
     {
      string f[];
      if(StringSplit(FileReadString(h), ',', f) >= 14 && f[6] == "FILLED" && StringLen(f[13]) > 0)
         HealthAdd(StringToDouble(f[13]));
     }
   FileClose(h);
   HealthEvaluate();
  }

#endif // CORB_HEALTH_MQH
