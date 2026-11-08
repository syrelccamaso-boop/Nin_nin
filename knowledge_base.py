"""
backend/knowledge_base.py - offline troubleshooting guide for the Computer
Laboratory (Centrum, IT Laboratory and CSSC Laboratory).

Used two ways by ai_service.py:
  1. The best matching entries are given to Gemini so its answer follows the
     lab's own procedures.
  2. When Gemini is down or slower than the deadline, the matching entry is
     shown to the teacher directly.

Entry format
------------
{
    "id":         unique short name
    "category":   Hardware | Software | Network | System | Other
    "priority":   Low | Medium | High
    "keywords":   words/phrases that point to this problem, in English,
                  Tagalog/Taglish and Bisaya, plus common misspellings.
                  A keyword matches the start of a word ("print" also matches
                  "printer"). Put "=" in front to match the whole word only
                  ("=lines" does not match "guidelines").
                  Typos of keywords with 5+ letters are matched automatically.
    "cause":      {"en": ..., "tl": ...}
    "steps":      [(action_en, check_en, action_tl, check_tl), ...]
    "solution":   {"en": ..., "tl": ...}
    "escalation": {"en": ..., "tl": ...}
}

Adding entries without editing this file
----------------------------------------
Put them in backend/kb_custom.json (a list of entries in the same format;
steps may be lists or {"action", "check", "action_tl", "check_tl"} objects).
An entry with the same id as a built-in one replaces it; {"id": "...",
"disabled": true} removes one. Call ai_service.reload_knowledge() to apply.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger("centrum.kb")

CUSTOM_KB_PATH = Path(__file__).with_name("kb_custom.json")

# Order matters only for ties: earlier entries win. Safety comes first.
BUILTIN_KB: list[dict] = [
    # --------------------------------------------------------------
    {
        "id": "electrical_hazard",
        "category": "Hardware",
        "priority": "High",
        "keywords": [
            "smoke", "smoking", "spark", "sparks", "sparking", "burning smell",
            "smells burning", "burnt smell", "electric shock", "got shocked",
            "=shock", "exposed wire", "naked wire", "melted", "fire",
            "usok", "umuusok", "may usok", "amoy sunog", "amoy nasusunog",
            "nasusunog", "nag spark", "nagspark", "kumislap ang saksakan",
            "nakuryente", "kinuryente", "may kuryente", "sunog",
            "naay aso", "nakuryentehan", "nasunog",
        ],
        "cause": {
            "en": "A damaged cable, outlet, extension/AVR or power supply. This is an electrical hazard.",
            "tl": "May sirang cable, saksakan, extension/AVR o power supply. Delikado ito sa kuryente.",
        },
        "steps": [
            ("Do NOT touch the computer, cables or outlet.",
             "Keep everyone, especially students, away from the area.",
             "HUWAG hawakan ang computer, cable o saksakan.",
             "Palayuin ang lahat, lalo na ang mga estudyante."),
            ("Only if you can do it without touching the damaged part, switch off the AVR/extension switch or the room's breaker.",
             "The smoke or sparks stop.",
             "Kung kaya lang nang hindi hinahawakan ang sirang parte, i-off ang switch ng AVR/extension o ang breaker ng room.",
             "Tumigil ang usok o spark."),
            ("If there are flames, leave the room and call building security; use a fire extinguisher only if you are trained.",
             "Everyone is out safely.",
             "Kung may apoy, lumabas ng room at tawagan ang security; gumamit lang ng fire extinguisher kung marunong.",
             "Ligtas na nakalabas ang lahat."),
            ("Report it right away with the PC number and room.",
             "The technician has been told.",
             "I-report agad kasama ang PC number at room.",
             "Nasabihan na ang technician."),
        ],
        "solution": {
            "en": "Leave the unit unplugged and unused until a technician inspects and repairs it.",
            "tl": "Huwag nang isaksak o gamitin hanggang ma-inspeksyon at maayos ng technician.",
        },
        "escalation": {
            "en": "Always contact the laboratory technician or administrator immediately. Never try to fix it yourself.",
            "tl": "Laging tawagan agad ang lab technician o administrator. Huwag itong subukang ayusin mag-isa.",
        },
    },
    # --------------------------------------------------------------
    {
        "id": "no_power",
        "category": "Hardware",
        "priority": "High",
        "keywords": [
            "won't turn on", "wont turn on", "will not turn on", "not turning on",
            "doesn't turn on", "does not turn on", "won't power on", "no power",
            "not powering", "dead pc", "pc is dead", "computer is dead",
            "won't start", "wont start", "power button", "turned off by itself",
            "ayaw mag on", "ayaw mag-on", "ayaw magon", "hindi mag on", "di mag on",
            "hindi nag o-on", "hindi nag oon", "di nag oon", "walang power",
            "ayaw bumukas", "hindi bumubukas", "di bumubukas", "ayaw magbukas",
            "bumukas ang pc", "bumukas ng pc", "bumukas yung pc",
            "bumukas ang computer", "bumukas ng computer", "bumukas yung computer",
            "patay ang pc", "patay yung pc", "patay ang computer", "patay na pc",
            "dili mo on", "dili mag on", "dili ma on", "walay power", "di mo abli",
        ],
        "cause": {
            "en": "Loose or unplugged power cable, AVR/extension switched off, a dead outlet, or a failed power supply.",
            "tl": "Maluwag o tanggal ang power cable, naka-off ang AVR/extension, walang kuryente ang saksakan, o sira ang power supply.",
        },
        "steps": [
            ("Make sure the power cable is firmly plugged into the back of the PC and into the AVR/extension.",
             "The cable does not move when gently pulled.",
             "Siguraduhing mahigpit ang pagkakasaksak ng power cable sa likod ng PC at sa AVR/extension.",
             "Hindi gumagalaw ang cable kapag bahagyang hinila."),
            ("Check that the AVR/extension is switched ON.",
             "Its light is on.",
             "Tingnan kung naka-ON ang AVR/extension.",
             "Nakailaw ito."),
            ("If the PC has a switch on the back (marked I/O), set it to I. Do not open the case.",
             "The switch is on I.",
             "Kung may switch sa likod ng PC (may markang I/O), ilagay sa I. Huwag buksan ang case.",
             "Nasa I ang switch."),
            ("Press the power button once and wait 10 seconds.",
             "The front light turns on or the fans spin.",
             "Pindutin nang isang beses ang power button at maghintay ng 10 segundo.",
             "Umiilaw ang ilaw sa harap o umiikot ang fan."),
            ("Plug the PC into a different outlet that you know works.",
             "The PC turns on from the other outlet.",
             "Isaksak ang PC sa ibang saksakang sigurado kang gumagana.",
             "Nag-on ang PC sa ibang saksakan."),
        ],
        "solution": {
            "en": "Fix the loose connection or use a working outlet. If the PC stays completely dead on a working outlet, the power supply or motherboard has likely failed.",
            "tl": "Ayusin ang maluwag na koneksyon o gumamit ng gumaganang saksakan. Kung patay pa rin kahit gumagana ang saksakan, malamang sira ang power supply o motherboard.",
        },
        "escalation": {
            "en": "Report it to the technician if there are no lights or fan sounds on a working outlet. Stop and report immediately if you notice a burning smell or sparks.",
            "tl": "I-report sa technician kung walang ilaw o tunog ng fan kahit gumagana ang saksakan. Itigil at i-report agad kung may amoy sunog o spark.",
        },
    },
    # --------------------------------------------------------------
    {
        "id": "no_display",
        "category": "Hardware",
        "priority": "Medium",
        "keywords": [
            "no display", "black screen", "blank screen", "no signal",
            "screen is black", "monitor is black", "monitor won't turn on",
            "monitor not working", "nothing on the screen", "check signal cable",
            "no input", "=monitor", "monitors",
            "walang display", "walang lumalabas sa monitor", "walang lumalabas sa screen",
            "itim ang screen", "itim yung screen", "itim lang", "black lang",
            "ayaw lumabas ng display", "patay ang monitor", "walay display",
            "itom ang screen", "walay mogawas",
        ],
        "cause": {
            "en": "Monitor off or asleep, loose video cable (HDMI/VGA/DisplayPort), wrong input, or a display hardware fault.",
            "tl": "Naka-off o naka-sleep ang monitor, maluwag ang video cable (HDMI/VGA/DisplayPort), maling input, o sira ang display hardware.",
        },
        "steps": [
            ("Press the monitor's own power button.",
             "The monitor's power light turns on.",
             "Pindutin ang power button ng monitor mismo.",
             "Umiilaw ang power light ng monitor."),
            ("Move the mouse or press a key to wake the PC from sleep.",
             "The screen lights up.",
             "Igalaw ang mouse o pumindot ng key para magising ang PC.",
             "Lumiwanag ang screen."),
            ("Check that the video cable is firmly connected at both the monitor and the PC.",
             "Both ends are tight; the 'No signal' message disappears.",
             "Tingnan kung mahigpit ang video cable sa monitor at sa PC.",
             "Mahigpit ang dalawang dulo; nawala ang 'No signal'."),
            ("Use the monitor's Input/Source button to pick the input the cable uses (HDMI, VGA or DP).",
             "The desktop appears.",
             "Gamitin ang Input/Source button ng monitor para piliin ang tamang input (HDMI, VGA o DP).",
             "Lumabas ang desktop."),
            ("Restart the PC.",
             "The startup logo appears on screen.",
             "I-restart ang PC.",
             "Lumabas ang logo sa pag-start."),
        ],
        "solution": {
            "en": "Reconnect the cable or select the correct input. If the screen stays black while the PC is on, the monitor, cable or graphics card needs checking.",
            "tl": "Ikabit muli ang cable o piliin ang tamang input. Kung itim pa rin habang naka-on ang PC, kailangang tingnan ang monitor, cable o graphics card.",
        },
        "escalation": {
            "en": "Contact the technician if the display stays black after these steps, or if the monitor will not power on at all.",
            "tl": "Tawagan ang technician kung itim pa rin pagkatapos ng mga hakbang, o kung hindi talaga nag-o-on ang monitor.",
        },
    },
    # --------------------------------------------------------------
    {
        "id": "display_quality",
        "category": "Hardware",
        "priority": "Low",
        "keywords": [
            "flicker", "flickering", "=lines", "lines on the screen", "line on screen",
            "blurry", "blurred", "too dark", "=dim", "brightness", "resolution",
            "stretched", "upside down", "rotated", "sideways", "icons too big",
            "text too small", "wrong colors", "wrong colours", "dead pixel",
            "screen tearing",
            "kumukurap", "kumikislap ang screen", "may linya", "may guhit",
            "malabo", "madilim ang screen", "baliktad ang screen", "nakabaliktad",
            "masyadong malaki", "lumaki ang icons", "kurap", "naay linya", "labo",
        ],
        "cause": {
            "en": "Loose video cable, wrong resolution or scaling, monitor settings, or a failing monitor.",
            "tl": "Maluwag ang video cable, maling resolution o scaling, setting ng monitor, o nasisira na ang monitor.",
        },
        "steps": [
            ("Push the video cable in firmly at both ends.",
             "Flickering or wrong colors stop.",
             "Idiin nang mahigpit ang video cable sa dalawang dulo.",
             "Nawala ang pagkurap o maling kulay."),
            ("Right-click the desktop > Display settings, and pick the Recommended resolution and scale.",
             "Text and icons look sharp and normal size.",
             "I-right-click ang desktop > Display settings, at piliin ang Recommended na resolution at scale.",
             "Malinaw at normal ang laki ng text at icons."),
            ("If the screen is upside down or sideways, set Display orientation to Landscape in the same window.",
             "The screen is upright.",
             "Kung baliktad o patagilid, gawing Landscape ang Display orientation sa parehong window.",
             "Tuwid na ang screen."),
            ("Use the monitor's menu button to adjust brightness or choose Reset.",
             "Brightness and colors look normal.",
             "Gamitin ang menu button ng monitor para ayusin ang brightness o piliin ang Reset.",
             "Normal na ang liwanag at kulay."),
        ],
        "solution": {
            "en": "Correct the cable and display settings. Lines or flicker that stay after this usually mean the monitor or cable must be replaced.",
            "tl": "Ayusin ang cable at display settings. Kung may linya o kurap pa rin, kadalasan kailangang palitan ang monitor o cable.",
        },
        "escalation": {
            "en": "Report it to the technician if lines, flicker or dead spots remain.",
            "tl": "I-report sa technician kung may linya, kurap o patay na bahagi pa rin.",
        },
    },
    # --------------------------------------------------------------
    {
        "id": "slow_pc",
        "category": "System",
        "priority": "Medium",
        "keywords": [
            "slow", "very slow", "laggy", "lagging", "=lag", "lags", "hang", "hangs",
            "hanging", "freeze", "freezes", "freezing", "frozen", "not responding",
            "takes forever", "loading forever", "stuck", "unresponsive",
            "mabagal", "bagal", "ang bagal", "nagla-lag", "naglalag", "nag lag",
            "nag hang", "naghahang", "nag-hang", "nagha-hang", "nagloloko",
            "nag freeze", "nagfreeze", "di gumagalaw", "hindi gumagalaw",
            "hinay", "hinay kaayo", "nag hang na", "ga hang", "ga lag",
        ],
        "cause": {
            "en": "Too many programs or browser tabs open, low memory, a full disk, background updates, or one program not responding.",
            "tl": "Sobrang daming bukas na programs o browser tabs, kulang ang memory, puno ang disk, may update sa background, o may isang program na hindi nagre-respond.",
        },
        "steps": [
            ("Save your work, then close programs and browser tabs you are not using.",
             "The PC responds faster.",
             "I-save ang ginagawa, tapos isara ang mga program at browser tab na hindi ginagamit.",
             "Bumilis ang PC."),
            ("Press Ctrl+Shift+Esc to open Task Manager and look at the CPU, Memory and Disk columns.",
             "You can see which program is using the most.",
             "Pindutin ang Ctrl+Shift+Esc para buksan ang Task Manager at tingnan ang CPU, Memory at Disk.",
             "Makikita kung aling program ang pinakamaraming ginagamit."),
            ("Select a program marked 'Not responding' (one you opened, not a Windows process) and click End task.",
             "The frozen window closes.",
             "Piliin ang program na 'Not responding' (yung binuksan mo, hindi Windows process) at i-click ang End task.",
             "Nagsara ang nag-freeze na window."),
            ("Restart the PC (Start > Power > Restart).",
             "It runs normally after restarting.",
             "I-restart ang PC (Start > Power > Restart).",
             "Normal na ang takbo pagkatapos mag-restart."),
            ("If 'Working on updates' appears, let it finish before using the PC.",
             "The update completes and speed returns.",
             "Kung may 'Working on updates', hayaang matapos bago gamitin ang PC.",
             "Natapos ang update at bumalik ang bilis."),
        ],
        "solution": {
            "en": "Keep only the programs you need open and restart the PC at least once a day. A PC that stays slow after a restart may need cleanup, more memory or a disk check.",
            "tl": "Buksan lang ang mga kailangang program at i-restart ang PC kahit isang beses kada araw. Kung mabagal pa rin pagka-restart, maaaring kailangan ng cleanup, dagdag na memory o disk check.",
        },
        "escalation": {
            "en": "Report it to the technician if the PC is still slow right after a restart, freezes often, or Disk stays at 100%.",
            "tl": "I-report sa technician kung mabagal pa rin kahit kaka-restart, madalas mag-freeze, o laging 100% ang Disk.",
        },
    },
    # --------------------------------------------------------------
    {
        "id": "blue_screen",
        "category": "System",
        "priority": "High",
        "keywords": [
            "blue screen", "bsod", "stop code", "ran into a problem",
            "critical process died", "memory management", "irql", "kernel",
            "restarts by itself", "restarting by itself", "keeps restarting",
            "random restart", "shuts down by itself", "turns off by itself",
            "blue na screen", "asul na screen", "nag blue screen", "nagbluescreen",
            "kusang nagre-restart", "kusang nagrerestart", "nagre-restart mag-isa",
            "namamatay mag-isa", "kusang namamatay", "kusang nag-o-off",
            "kalit ra mo restart", "kalit mamatay",
        ],
        "cause": {
            "en": "A driver, memory, disk or overheating problem made Windows stop to protect itself.",
            "tl": "May problema sa driver, memory, disk o sobrang init kaya huminto ang Windows para protektahan ang sarili.",
        },
        "steps": [
            ("Take a photo of the blue screen or write down the stop code.",
             "You have the exact code (e.g. CRITICAL_PROCESS_DIED).",
             "Kunan ng litrato ang blue screen o isulat ang stop code.",
             "Nakuha ang eksaktong code (hal. CRITICAL_PROCESS_DIED)."),
            ("Remove any USB device that was plugged in recently.",
             "Only keyboard and mouse remain connected.",
             "Tanggalin ang anumang USB device na kakakabit lang.",
             "Keyboard at mouse na lang ang nakakabit."),
            ("Let the PC restart once.",
             "Windows starts normally.",
             "Hayaang mag-restart nang isang beses ang PC.",
             "Normal na nag-start ang Windows."),
            ("Note what you were doing when it happened.",
             "You can tell the technician the program or action.",
             "Tandaan kung ano ang ginagawa nang mangyari ito.",
             "Masasabi sa technician ang program o ginawa."),
        ],
        "solution": {
            "en": "A single blue screen can be a one-off. If it repeats, the driver, memory or disk needs a technician's diagnosis.",
            "tl": "Ang isang beses na blue screen ay maaaring nagkataon lang. Kung umuulit, kailangang suriin ng technician ang driver, memory o disk.",
        },
        "escalation": {
            "en": "Report it with the stop code if it happens more than once, or if the PC restarts or shuts down by itself repeatedly.",
            "tl": "I-report kasama ang stop code kung higit sa isang beses nangyari, o kung paulit-ulit na kusang nagre-restart o namamatay.",
        },
    },
    # --------------------------------------------------------------
    {
        "id": "boot_failure",
        "category": "System",
        "priority": "High",
        "keywords": [
            "no bootable device", "boot device", "automatic repair",
            "preparing automatic repair", "boot loop", "bootloop",
            "stuck on logo", "stuck at logo", "stuck on loading", "stuck loading",
            "operating system not found", "disk boot failure", "bios", "won't boot",
            "not booting", "boot", "inaccessible boot device",
            "ayaw mag boot", "hindi mag boot", "di mag boot", "stuck sa logo",
            "stuck sa loading", "paikot-ikot lang", "umiikot lang", "loading lang",
            "naka-stuck sa loading", "ayaw tumuloy",
        ],
        "cause": {
            "en": "A USB drive left plugged in, an interrupted update, disk errors, or a damaged Windows installation.",
            "tl": "May naiwang USB, naputol na update, error sa disk, o sira ang Windows installation.",
        },
        "steps": [
            ("Remove all USB drives and discs, then restart.",
             "Windows starts normally.",
             "Tanggalin lahat ng USB at disc, tapos i-restart.",
             "Normal na nag-start ang Windows."),
            ("If it says 'Working on updates' or 'Automatic repair', wait at least 15 minutes without turning it off.",
             "It finishes and reaches the login screen.",
             "Kung 'Working on updates' o 'Automatic repair' ang nakalagay, maghintay ng 15 minuto nang hindi ino-off.",
             "Natapos at umabot sa login screen."),
            ("Write down or photograph the exact message on screen.",
             "You have the exact text.",
             "Isulat o kunan ng litrato ang eksaktong mensahe sa screen.",
             "Nakuha ang eksaktong text."),
            ("Do not change BIOS settings or try to reinstall Windows.",
             "Settings are left as they were.",
             "Huwag baguhin ang BIOS settings o subukang i-reinstall ang Windows.",
             "Walang binago sa settings."),
        ],
        "solution": {
            "en": "Removing a forgotten USB often fixes it. Otherwise the disk or Windows needs repair by the technician.",
            "tl": "Madalas naaayos ito kapag tinanggal ang naiwang USB. Kung hindi, kailangang ayusin ng technician ang disk o Windows.",
        },
        "escalation": {
            "en": "Report it with the exact message if the PC still does not reach the login screen. Use another PC in the meantime.",
            "tl": "I-report kasama ang eksaktong mensahe kung hindi pa rin umaabot sa login screen. Gumamit muna ng ibang PC.",
        },
    },
    # --------------------------------------------------------------
    {
        "id": "network",
        "category": "Network",
        "priority": "Medium",
        "keywords": [
            "internet", "no internet", "wifi", "wi-fi", "=lan", "ethernet", "network",
            "offline", "no connection", "can't connect", "cannot connect",
            "not connected", "limited connection", "=dns", "slow internet",
            "website won't load", "page won't load", "site can't be reached",
            "connection timed out", "disconnected",
            "walang internet", "walang net", "walang wifi", "walang connection",
            "mahina ang internet", "mahina net", "mahina ang wifi",
            "mabagal ang internet", "mabagal internet", "mabagal ang net",
            "di maka connect", "hindi maka connect", "hindi makaconnect",
            "di makaconnect", "naputol ang internet", "nawala ang internet",
            "nawalan ng internet", "walay internet", "walay net", "hinay ang internet",
            "di ka connect",
        ],
        "cause": {
            "en": "Loose LAN cable, Wi-Fi switched off, a network setting problem on this PC, or an outage affecting the whole lab.",
            "tl": "Maluwag ang LAN cable, naka-off ang Wi-Fi, problema sa network setting ng PC, o outage sa buong lab.",
        },
        "steps": [
            ("Check whether other PCs in the room have internet.",
             "You know if it is only this PC or the whole room.",
             "Tingnan kung may internet ang ibang PC sa room.",
             "Alam na kung itong PC lang o buong room."),
            ("Check the LAN cable at the back of the PC and at the wall/table port.",
             "The cable clicks in and the port light blinks.",
             "Tingnan ang LAN cable sa likod ng PC at sa port sa pader/mesa.",
             "Naka-click ang cable at kumukurap ang ilaw ng port."),
            ("For Wi-Fi, click the network icon on the taskbar, make sure Wi-Fi is on and Airplane mode is off, then connect to the lab network.",
             "It shows 'Connected'.",
             "Kung Wi-Fi, i-click ang network icon sa taskbar, siguraduhing naka-on ang Wi-Fi at naka-off ang Airplane mode, tapos kumonekta sa lab network.",
             "Nakalagay na 'Connected'."),
            ("Right-click the network icon > Troubleshoot problems (Network and Internet).",
             "Windows reports it fixed the problem.",
             "I-right-click ang network icon > Troubleshoot problems (Network and Internet).",
             "Sinabi ng Windows na naayos na."),
            ("Restart the PC.",
             "Websites load after restarting.",
             "I-restart ang PC.",
             "Nagbubukas na ang mga website pagka-restart."),
        ],
        "solution": {
            "en": "Reconnect the cable or Wi-Fi on this PC. If every PC in the room is offline, it is a lab network outage, not a PC problem.",
            "tl": "Ikabit muli ang cable o Wi-Fi sa PC. Kung lahat ng PC sa room ay walang internet, outage ito sa network ng lab, hindi sira ng PC.",
        },
        "escalation": {
            "en": "Contact the technician or administrator if the whole room is offline or this PC still has no internet. Do not touch the network switch or router.",
            "tl": "Tawagan ang technician o administrator kung buong room ang walang internet o wala pa rin sa PC na ito. Huwag galawin ang network switch o router.",
        },
    },
    # --------------------------------------------------------------
    {
        "id": "browser_online_class",
        "category": "Software",
        "priority": "Low",
        "keywords": [
            "browser", "chrome", "google chrome", "=edge", "microsoft edge", "firefox",
            "website", "=site", "webpage", "blocked site", "site is blocked",
            "access denied", "=404", "=403", "cookies", "cache", "youtube",
            "google classroom", "canvas", "moodle", "=lms", "teams",
            "zoom", "google meet", "gmeet", "=meet", "portal",
            "naka block", "naka-block", "blocked", "ayaw mag load", "hindi nag lo-load",
            "di nag load", "hindi bumubukas ang site", "hindi bumubukas ang website",
        ],
        "cause": {
            "en": "A browser cache or extension problem, a site blocked by the lab's filter, a wrong address, or the site itself is down.",
            "tl": "Problema sa cache o extension ng browser, naka-block ang site sa filter ng lab, maling address, o down ang site mismo.",
        },
        "steps": [
            ("Check that other websites open.",
             "If none open, follow the internet steps instead.",
             "Tingnan kung nagbubukas ang ibang website.",
             "Kung walang nagbubukas, sundin ang steps para sa internet."),
            ("Press Ctrl+F5 to reload the page fully.",
             "The page loads.",
             "Pindutin ang Ctrl+F5 para i-reload nang buo ang page.",
             "Nag-load ang page."),
            ("Open the same address in a private/incognito window (Ctrl+Shift+N) or another browser.",
             "It works there, so the problem is the browser's cache or extensions.",
             "Buksan ang address sa private/incognito window (Ctrl+Shift+N) o ibang browser.",
             "Gumagana doon, kaya cache o extension ng browser ang problema."),
            ("Clear browsing data: Ctrl+Shift+Delete > Cookies and Cached images > Clear.",
             "The site loads normally.",
             "I-clear ang browsing data: Ctrl+Shift+Delete > Cookies at Cached images > Clear.",
             "Normal nang nagbubukas ang site."),
        ],
        "solution": {
            "en": "Use a clean browser window or clear the cache. If the page says it is blocked, the lab's web filter needs an exception.",
            "tl": "Gumamit ng malinis na browser window o i-clear ang cache. Kung naka-block ang page, kailangan ng exception sa web filter ng lab.",
        },
        "escalation": {
            "en": "Ask the administrator to unblock a site you need for class. Contact the technician if no browser works on this PC.",
            "tl": "Hilingin sa administrator na i-unblock ang site na kailangan sa klase. Tawagan ang technician kung walang browser na gumagana sa PC.",
        },
    },
    # --------------------------------------------------------------
    {
        "id": "keyboard_mouse",
        "category": "Hardware",
        "priority": "Low",
        "keywords": [
            "keyboard", "keybaord", "mouse", "cursor", "pointer", "keys not working",
            "key not working", "stuck key", "can't type", "cannot type",
            "typing wrong letters", "num lock", "numlock", "caps lock", "touchpad",
            "wireless mouse", "double click", "scroll wheel",
            "sira ang keyboard", "sira keyboard", "sira ang mouse", "sira mouse",
            "ayaw gumana ng mouse", "ayaw gumana ng keyboard", "hindi makapag type",
            "di makatype", "walang cursor", "hindi gumagalaw ang cursor",
            "di gumagalaw ang mouse", "guba ang mouse", "guba ang keyboard",
        ],
        "cause": {
            "en": "A loose USB plug, a bad USB port, dead batteries (wireless), Num Lock off, or a worn-out keyboard or mouse.",
            "tl": "Maluwag na USB, sirang USB port, lowbat (kung wireless), naka-off ang Num Lock, o luma na ang keyboard o mouse.",
        },
        "steps": [
            ("Unplug the keyboard or mouse and plug it into a different USB port, preferably at the back of the PC.",
             "Its light turns on or Windows makes a connect sound.",
             "Tanggalin ang keyboard o mouse at isaksak sa ibang USB port, mas maganda sa likod ng PC.",
             "Umiilaw ito o may tunog ng pagkakonekta."),
            ("For wireless devices, check the batteries and the small USB receiver.",
             "The device responds.",
             "Kung wireless, tingnan ang baterya at ang maliit na USB receiver.",
             "Gumagana na ang device."),
            ("If numbers don't type, press Num Lock; if letters are all capitals, press Caps Lock.",
             "Typing is correct.",
             "Kung ayaw lumabas ng numbers, pindutin ang Num Lock; kung puro capital, pindutin ang Caps Lock.",
             "Tama na ang na-ta-type."),
            ("Restart the PC.",
             "The device works after restarting.",
             "I-restart ang PC.",
             "Gumagana na pagka-restart."),
        ],
        "solution": {
            "en": "Reconnect to a working port. If it fails on every port, the keyboard or mouse needs replacing; ask the technician for a spare.",
            "tl": "Ikabit sa gumaganang port. Kung ayaw sa lahat ng port, kailangang palitan ang keyboard o mouse; humingi ng spare sa technician.",
        },
        "escalation": {
            "en": "Report it to the technician if the device does not work on any port or on another PC.",
            "tl": "I-report sa technician kung hindi gumagana sa kahit anong port o sa ibang PC.",
        },
    },
    # --------------------------------------------------------------
    {
        "id": "audio",
        "category": "Hardware",
        "priority": "Low",
        "keywords": [
            "sound", "audio", "speaker", "speakers", "headset", "headphone",
            "headphones", "earphone", "earphones", "=mic", "microphone", "no sound",
            "can't hear", "cannot hear", "volume", "muted", "=mute", "echo",
            "static noise",
            "walang sound", "walang tunog", "walang audio", "hindi marinig",
            "di marinig", "mahina ang sound", "mahina ang tunog", "walang boses",
            "ayaw ng mic", "hindi gumagana ang mic", "walay tingog", "walay sound",
            "dili madungog",
        ],
        "cause": {
            "en": "Volume muted, the wrong playback or recording device selected, a loose plug, or microphone access blocked.",
            "tl": "Naka-mute, maling playback o recording device ang napili, maluwag ang saksak, o naka-block ang access ng mic.",
        },
        "steps": [
            ("Click the speaker icon on the taskbar and make sure it is not muted and the volume is up.",
             "The slider is above zero with no X on the icon.",
             "I-click ang speaker icon sa taskbar at siguraduhing hindi naka-mute at malakas ang volume.",
             "Mas mataas sa zero ang slider at walang X sa icon."),
            ("In the same panel, choose the correct output device (headset or speakers).",
             "Sound plays from the right device.",
             "Sa parehong panel, piliin ang tamang output device (headset o speakers).",
             "Lumalabas ang tunog sa tamang device."),
            ("Re-plug the headset: green jack = sound, pink jack = mic; or try another USB port.",
             "Windows detects the headset.",
             "Isaksak muli ang headset: green na jack = tunog, pink na jack = mic; o subukan sa ibang USB port.",
             "Na-detect ng Windows ang headset."),
            ("For the mic, open Settings > Privacy > Microphone and allow access; check the app isn't muting you.",
             "The mic level moves when you speak.",
             "Para sa mic, buksan ang Settings > Privacy > Microphone at i-allow; tingnan kung hindi ka naka-mute sa app.",
             "Gumagalaw ang mic level kapag nagsasalita."),
        ],
        "solution": {
            "en": "Unmute and select the right device. If there's still no sound with a known-good headset, the audio port or driver needs checking.",
            "tl": "I-unmute at piliin ang tamang device. Kung wala pa ring tunog kahit maayos ang headset, kailangang tingnan ang audio port o driver.",
        },
        "escalation": {
            "en": "Report it to the technician if no device produces sound after these steps.",
            "tl": "I-report sa technician kung walang tunog sa kahit anong device pagkatapos ng mga hakbang.",
        },
    },
    # --------------------------------------------------------------
    {
        "id": "printer",
        "category": "Hardware",
        "priority": "Medium",
        "keywords": [
            "print", "printer", "printing", "paper jam", "=jam", "jammed", "=ink",
            "toner", "printer offline", "print queue", "faded print",
            "naipit ang papel", "naipit papel", "naipit ang bond paper",
            "ayaw mag print", "hindi mag print", "di maka print", "di makaprint",
            "hindi makaprint", "walang lumalabas sa printer", "malabo ang print",
            "ubos ang ink", "dili mo print",
        ],
        "cause": {
            "en": "Printer off or offline, the wrong printer selected, a stuck print queue, a paper jam, or low ink/toner.",
            "tl": "Naka-off o offline ang printer, maling printer ang napili, stuck ang print queue, may naipit na papel, o paubos ang ink/toner.",
        },
        "steps": [
            ("Check the printer is on, has paper, and shows no blinking error light.",
             "The ready light is steady.",
             "Tingnan kung naka-on ang printer, may papel, at walang kumukurap na error light.",
             "Steady ang ready light."),
            ("In the Print window, make sure the lab's printer is selected, not 'Microsoft Print to PDF'.",
             "The correct printer name is shown.",
             "Sa Print window, siguraduhing ang printer ng lab ang napili, hindi 'Microsoft Print to PDF'.",
             "Tamang printer ang nakalagay."),
            ("Open Settings > Printers & scanners > the printer > Open print queue, and cancel all stuck jobs.",
             "The queue is empty.",
             "Buksan ang Settings > Printers & scanners > ang printer > Open print queue, at i-cancel ang mga naka-stuck.",
             "Wala nang laman ang queue."),
            ("Turn the printer off for 30 seconds, then on, and print again.",
             "The page prints.",
             "I-off ang printer nang 30 segundo, i-on muli, at mag-print ulit.",
             "Nag-print na."),
            ("For a paper jam: turn the printer off, open the doors shown on its panel, and pull the paper out slowly in the direction it travels. Never use sharp objects.",
             "No paper remains inside and the jam light is off.",
             "Kung may naipit: i-off ang printer, buksan ang pinto na nakaturo sa panel, at dahan-dahang hilahin ang papel pasunod sa daan nito. Huwag gumamit ng matulis na bagay.",
             "Wala nang papel sa loob at patay na ang jam light."),
        ],
        "solution": {
            "en": "Clear the queue or the jam and print again. Faded prints or an ink/toner warning mean the cartridge needs replacing by the technician.",
            "tl": "I-clear ang queue o ang naipit na papel at mag-print ulit. Kung malabo o may babala sa ink/toner, kailangang palitan ng technician ang cartridge.",
        },
        "escalation": {
            "en": "Contact the technician for ink/toner, paper torn inside the printer, or error codes that stay after a restart.",
            "tl": "Tawagan ang technician para sa ink/toner, papel na napunit sa loob, o error code na nananatili kahit na-restart.",
        },
    },
    # --------------------------------------------------------------
    {
        "id": "projector",
        "category": "Hardware",
        "priority": "Medium",
        "keywords": [
            "projector", "projecter", "=hdmi", "=vga", "screen mirroring", "mirror",
            "duplicate screen", "extend screen", "second screen", "external display",
            "smart tv", "=tv", "win+p", "presentation screen",
            "walang lumalabas sa projector", "ayaw lumabas sa projector",
            "hindi lumalabas sa projector", "ayaw ng projector", "sira ang projector",
            "walay gawas sa projector",
        ],
        "cause": {
            "en": "Wrong input source on the projector, a loose HDMI/VGA cable, or the PC not set to show on a second screen.",
            "tl": "Maling input source sa projector, maluwag ang HDMI/VGA cable, o hindi naka-set ang PC na mag-display sa pangalawang screen.",
        },
        "steps": [
            ("Turn the projector on and wait about a minute for the lamp to warm up.",
             "The projector shows its logo or a 'No signal' message.",
             "I-on ang projector at maghintay ng mga isang minuto para uminit ang lamp.",
             "Lumalabas ang logo o 'No signal' sa projector."),
            ("Press Source/Input on the projector or remote and choose the port the cable uses (e.g. HDMI 1).",
             "The computer screen appears.",
             "Pindutin ang Source/Input sa projector o remote at piliin ang port na gamit ng cable (hal. HDMI 1).",
             "Lumabas ang screen ng computer."),
            ("Check the cable is firmly connected at both ends.",
             "Both ends are tight.",
             "Tingnan kung mahigpit ang cable sa dalawang dulo.",
             "Mahigpit ang dalawang dulo."),
            ("On the PC press Windows + P and choose Duplicate.",
             "The same screen shows on the PC and projector.",
             "Sa PC, pindutin ang Windows + P at piliin ang Duplicate.",
             "Parehong screen ang nasa PC at projector."),
            ("Unplug and re-plug the cable while the PC is on, or try another cable.",
             "The picture appears.",
             "Tanggalin at isaksak muli ang cable habang naka-on ang PC, o subukan ang ibang cable.",
             "Lumabas ang larawan."),
        ],
        "solution": {
            "en": "Select the right input and use Windows + P > Duplicate. If nothing works with a known-good cable, the projector or its port needs checking.",
            "tl": "Piliin ang tamang input at gamitin ang Windows + P > Duplicate. Kung wala pa rin kahit maayos ang cable, kailangang tingnan ang projector o ang port nito.",
        },
        "escalation": {
            "en": "Contact the technician if the projector will not turn on, its lamp light blinks red, or no image appears after these steps.",
            "tl": "Tawagan ang technician kung hindi nag-o-on ang projector, kumukurap na pula ang lamp light, o walang lumalabas pagkatapos ng mga hakbang.",
        },
    },
    # --------------------------------------------------------------
    {
        "id": "camera",
        "category": "Hardware",
        "priority": "Low",
        "keywords": [
            "camera", "webcam", "=cam", "video call", "no video", "camera not detected",
            "walang camera", "ayaw ng camera", "itim ang camera", "hindi makita sa camera",
        ],
        "cause": {
            "en": "Camera access turned off in Windows, another app using the camera, a closed privacy shutter, or a loose USB camera.",
            "tl": "Naka-off ang camera access sa Windows, may ibang app na gumagamit ng camera, nakasara ang takip, o maluwag ang USB camera.",
        },
        "steps": [
            ("Check the camera's privacy cover or shutter is open.",
             "The lens is uncovered.",
             "Tingnan kung bukas ang takip o shutter ng camera.",
             "Walang nakatakip sa lente."),
            ("Close other apps that may be using the camera (Zoom, Meet, Teams, Camera app).",
             "Only one app uses the camera.",
             "Isara ang ibang app na maaaring gumagamit ng camera (Zoom, Meet, Teams, Camera app).",
             "Isang app lang ang gumagamit ng camera."),
            ("Open Settings > Privacy > Camera and allow camera access for apps and the browser.",
             "Access is On.",
             "Buksan ang Settings > Privacy > Camera at i-allow ang access para sa apps at browser.",
             "Naka-On ang access."),
            ("In the meeting app's settings, select the correct camera; re-plug a USB camera if needed.",
             "Your video appears.",
             "Sa settings ng meeting app, piliin ang tamang camera; isaksak muli ang USB camera kung kailangan.",
             "Lumabas na ang video mo."),
        ],
        "solution": {
            "en": "Allow camera access and select the right device. If no app can see the camera, it or its driver needs checking.",
            "tl": "I-allow ang camera access at piliin ang tamang device. Kung walang app na nakakakita sa camera, kailangang tingnan ito o ang driver.",
        },
        "escalation": {
            "en": "Report it to the technician if the camera is not detected in any app.",
            "tl": "I-report sa technician kung hindi na-de-detect ang camera sa kahit anong app.",
        },
    },
    # --------------------------------------------------------------
    {
        "id": "app_problem",
        "category": "Software",
        "priority": "Medium",
        "keywords": [
            "application", "=app", "=apps", "=program", "=programs", "software", "won't open",
            "wont open", "doesn't open", "not opening", "can't open", "crash",
            "crashes", "crashing", "closes by itself", "error message", "not installed",
            "missing program", "ms word", "microsoft word", "excel", "powerpoint",
            "ms office", "microsoft office", "activate", "activation", "unlicensed",
            "product key", "visual studio", "vs code", "vscode", "netbeans", "python",
            "=java", "eclipse", "android studio", "autocad", "photoshop", "packet tracer",
            "xampp", "mysql", "=dll", "runtime error",
            "ayaw bumukas ng app", "ayaw bumukas ang app", "ayaw bumukas ng program",
            "hindi bumubukas ang app", "nagsasara mag-isa", "nag crash", "nagka-crash",
            "walang naka-install", "hindi naka install", "wala ang app", "may error",
            "nag error", "nag-eerror",
        ],
        "cause": {
            "en": "The program crashed, is not installed or licensed on this PC, or has a corrupted setting or update.",
            "tl": "Nag-crash ang program, hindi naka-install o walang lisensya sa PC na ito, o may sirang setting o update.",
        },
        "steps": [
            ("Close the program completely (check Task Manager) and open it again.",
             "It opens normally.",
             "Isara nang buo ang program (tingnan sa Task Manager) at buksan muli.",
             "Normal na bumukas."),
            ("Write down or photograph the exact error message.",
             "You have the exact text.",
             "Isulat o kunan ng litrato ang eksaktong error message.",
             "Nakuha ang eksaktong text."),
            ("Restart the PC and try again.",
             "The program works after restarting.",
             "I-restart ang PC at subukan ulit.",
             "Gumagana na pagka-restart."),
            ("Check whether the same program opens on another lab PC.",
             "You know if it is only this PC.",
             "Tingnan kung bumubukas ang parehong program sa ibang PC sa lab.",
             "Alam na kung itong PC lang."),
        ],
        "solution": {
            "en": "Reopening or restarting fixes most crashes. Missing, unlicensed or broken programs must be installed or repaired by the technician; do not install software yourself.",
            "tl": "Kadalasan naaayos sa pag-reopen o pag-restart. Ang wala, walang lisensya o sirang program ay dapat i-install o ayusin ng technician; huwag mag-install ng software mag-isa.",
        },
        "escalation": {
            "en": "Request installation or repair from the technician, with the program name, PC number and error message.",
            "tl": "Humiling ng installation o repair sa technician, kasama ang pangalan ng program, PC number at error message.",
        },
    },
    # --------------------------------------------------------------
    {
        "id": "login",
        "category": "System",
        "priority": "Medium",
        "keywords": [
            "password", "pasword", "forgot password", "forgot my password", "login",
            "log in", "sign in", "signin", "can't log in", "cannot log in",
            "locked out", "account locked", "username", "wrong password",
            "incorrect password", "temporary profile", "=pin", "user profile",
            "nakalimutan ang password", "nakalimutan password", "nakalimutan ko",
            "hindi maka login", "di maka login", "di makalogin", "hindi makalogin",
            "ayaw mag login", "mali ang password", "na-lock", "nalock", "naka lock",
            "nalimtan ang password", "dili maka login",
        ],
        "cause": {
            "en": "A mistyped password (Caps Lock or wrong keyboard language), a locked account after too many tries, or a profile problem.",
            "tl": "Mali ang pagkaka-type ng password (Caps Lock o maling keyboard language), na-lock ang account dahil sa daming subok, o problema sa profile.",
        },
        "steps": [
            ("Check Caps Lock and Num Lock, and that the keyboard language shows ENG.",
             "The keyboard lights and language are correct.",
             "Tingnan ang Caps Lock at Num Lock, at na ENG ang keyboard language.",
             "Tama ang ilaw ng keyboard at ang language."),
            ("Click the eye icon to show the password while typing it.",
             "The password shows exactly as intended.",
             "I-click ang eye icon para makita ang password habang tina-type.",
             "Tama ang lumalabas na password."),
            ("Use the exact username format the lab gave you.",
             "The username is accepted.",
             "Gamitin ang eksaktong format ng username na ibinigay ng lab.",
             "Tinanggap ang username."),
            ("If the account is locked, wait 15-30 minutes before trying again; do not keep guessing.",
             "Login works after waiting.",
             "Kung naka-lock, maghintay ng 15-30 minuto bago sumubok ulit; huwag manghula nang paulit-ulit.",
             "Naka-login na pagkatapos maghintay."),
            ("If Windows says you're signed in with a temporary profile, sign out and restart.",
             "Your normal desktop and files return.",
             "Kung sinabi ng Windows na temporary profile ang gamit, mag-sign out at i-restart.",
             "Bumalik ang normal na desktop at files."),
        ],
        "solution": {
            "en": "Retype carefully with the right keyboard settings. Forgotten passwords can only be reset by the administrator. Never share your password.",
            "tl": "I-type muli nang maingat gamit ang tamang keyboard settings. Ang administrator lang ang makakapag-reset ng nakalimutang password. Huwag ibigay ang password sa iba.",
        },
        "escalation": {
            "en": "Ask the administrator for a password reset or unlock (bring your ID).",
            "tl": "Humingi ng password reset o unlock sa administrator (dalhin ang ID).",
        },
    },
    # --------------------------------------------------------------
    {
        "id": "usb_storage",
        "category": "Hardware",
        "priority": "Low",
        "keywords": [
            "usb", "flash drive", "flashdrive", "flash disk", "thumb drive",
            "pendrive", "pen drive", "external drive", "external hard drive",
            "=sd card", "memory card", "not detected", "not recognized",
            "need to format", "format the disk",
            "hindi ma-detect", "hindi ma detect", "di ma detect", "di madetect",
            "hindi nababasa", "ayaw mabasa", "hindi lumalabas ang flash drive",
            "dili ma detect",
        ],
        "cause": {
            "en": "A bad USB port, a damaged or unsafely removed drive, or USB storage restricted by lab policy.",
            "tl": "Sirang USB port, sira o hindi maayos na natanggal na drive, o naka-restrict ang USB sa patakaran ng lab.",
        },
        "steps": [
            ("Plug the drive into a different USB port, preferably at the back of the PC.",
             "Windows makes a connect sound.",
             "Isaksak ang drive sa ibang USB port, mas maganda sa likod ng PC.",
             "May tunog ng pagkakonekta."),
            ("Open File Explorer > This PC.",
             "The drive appears with a letter (e.g. E:).",
             "Buksan ang File Explorer > This PC.",
             "Lumabas ang drive na may letter (hal. E:)."),
            ("If Windows asks to format the drive, click Cancel. Formatting erases everything.",
             "Your files are untouched.",
             "Kung pinapa-format ng Windows ang drive, i-click ang Cancel. Mabubura lahat kapag na-format.",
             "Buo pa ang files mo."),
            ("Try the drive on another PC.",
             "You know if the drive or this PC is the problem.",
             "Subukan ang drive sa ibang PC.",
             "Alam na kung ang drive o ang PC ang may problema."),
        ],
        "solution": {
            "en": "Use a working port and always use 'Safely remove' before unplugging. A drive that asks to be formatted everywhere is damaged; get help before formatting if the files matter.",
            "tl": "Gumamit ng gumaganang port at laging i-'Safely remove' bago tanggalin. Kung pinapa-format kahit saan, sira ang drive; magpatulong muna bago i-format kung mahalaga ang files.",
        },
        "escalation": {
            "en": "Contact the technician if no USB drive works on this PC (ports may be disabled by policy) or to try recovering important files.",
            "tl": "Tawagan ang technician kung walang USB na gumagana sa PC (maaaring naka-disable ang ports) o para subukang i-recover ang mahahalagang files.",
        },
    },
    # --------------------------------------------------------------
    {
        "id": "virus_malware",
        "category": "Software",
        "priority": "High",
        "keywords": [
            "virus", "malware", "popup", "pop-up", "pop up", "pop ups", "=ads",
            "adware", "ransomware", "hacked", "suspicious", "files encrypted",
            "shortcut virus", "files became shortcuts", "antivirus",
            "windows defender", "defender", "trojan", "spyware", "scam",
            "may virus", "na-virus", "navirus", "nagka virus", "naging shortcut",
            "naging shortcut ang files", "kakaibang ads", "na hack", "nahack",
            "naay virus",
        ],
        "cause": {
            "en": "Malicious software, often from an infected flash drive, a fake download, or a harmful website.",
            "tl": "Malisyosong software, kadalasan galing sa may virus na flash drive, pekeng download, o masamang website.",
        },
        "steps": [
            ("Do not click pop-ups or enter any password or personal information.",
             "Nothing is clicked or typed.",
             "Huwag i-click ang pop-up at huwag maglagay ng password o personal na impormasyon.",
             "Walang na-click o na-type."),
            ("If a message says your files are encrypted or demands payment, unplug the LAN cable (or turn off Wi-Fi) immediately.",
             "The PC is disconnected from the network.",
             "Kung may mensaheng naka-encrypt ang files o humihingi ng bayad, tanggalin agad ang LAN cable (o i-off ang Wi-Fi).",
             "Naka-disconnect na sa network ang PC."),
            ("Remove your flash drive and do not use it on other PCs until it is scanned.",
             "The drive is set aside.",
             "Tanggalin ang flash drive at huwag gamitin sa ibang PC hanggang ma-scan.",
             "Naitabi ang drive."),
            ("If allowed, open Windows Security > Virus & threat protection > Quick scan.",
             "The scan finishes and lists any threats.",
             "Kung pinapayagan, buksan ang Windows Security > Virus & threat protection > Quick scan.",
             "Natapos ang scan at nakalista ang threats."),
        ],
        "solution": {
            "en": "Stop using the PC and let the technician clean or restore it. Scan your flash drive before using it anywhere else.",
            "tl": "Itigil ang paggamit ng PC at hayaang linisin o i-restore ng technician. I-scan muna ang flash drive bago gamitin sa iba.",
        },
        "escalation": {
            "en": "Report it to the technician immediately with the PC number, especially for encrypted files or ransom messages.",
            "tl": "I-report agad sa technician kasama ang PC number, lalo na kung naka-encrypt ang files o may ransom message.",
        },
    },
    # --------------------------------------------------------------
    {
        "id": "storage_full",
        "category": "System",
        "priority": "Medium",
        "keywords": [
            "disk full", "storage full", "low disk space", "no space", "not enough space",
            "out of space", "c drive full", "drive is full", "drive full", "disk space",
            "puno na ang storage", "puno ang storage", "puno na ang disk",
            "walang space", "kulang ang space", "kulang space", "wala nang space",
            "puno na ang c",
        ],
        "cause": {
            "en": "The drive is filled by downloads, saved files, temporary files or a pending update.",
            "tl": "Napuno ang drive ng downloads, naka-save na files, temporary files o update.",
        },
        "steps": [
            ("Move your own files from Desktop, Downloads and Documents to your flash drive or cloud storage.",
             "Your files are safely copied elsewhere.",
             "Ilipat ang sarili mong files mula Desktop, Downloads at Documents sa flash drive o cloud.",
             "Ligtas nang nakopya ang files mo."),
            ("Delete only your own files from this PC after copying them.",
             "Free space increases (check This PC).",
             "Burahin lang ang sarili mong files sa PC pagkatapos makopya.",
             "Lumaki ang free space (tingnan sa This PC)."),
            ("Search for Disk Cleanup, select drive C:, tick Temporary files, and run it.",
             "More free space appears.",
             "I-search ang Disk Cleanup, piliin ang drive C:, i-check ang Temporary files, at i-run.",
             "Mas lumaki ang free space."),
        ],
        "solution": {
            "en": "Keep personal files on a flash drive or cloud, not on lab PCs. Never delete system files or other users' files.",
            "tl": "Itabi ang personal na files sa flash drive o cloud, hindi sa lab PC. Huwag burahin ang system files o files ng ibang user.",
        },
        "escalation": {
            "en": "Report it to the technician if the drive is still almost full after cleanup.",
            "tl": "I-report sa technician kung halos puno pa rin pagkatapos ng cleanup.",
        },
    },
    # --------------------------------------------------------------
    {
        "id": "lost_file",
        "category": "Software",
        "priority": "Medium",
        "keywords": [
            "lost file", "lost my file", "deleted", "accidentally deleted",
            "missing file", "file is gone", "file disappeared", "unsaved",
            "not saved", "didn't save", "recover", "recycle bin", "corrupted",
            "corrupt", "file won't open", "can't open file", "deep freeze",
            "files gone after restart",
            "nawala ang file", "nawala file", "nawala ang files", "na-delete",
            "nadelete", "nabura", "burado", "hindi na-save", "di na save",
            "hindi nasave", "nawala ang ginawa ko", "nawala ang project",
            "nawala akong file",
        ],
        "cause": {
            "en": "The file was deleted, saved somewhere else, never saved, or erased because lab PCs reset themselves on restart.",
            "tl": "Nabura ang file, na-save sa ibang lugar, hindi na-save, o nabura dahil nagre-reset ang lab PC tuwing nire-restart.",
        },
        "steps": [
            ("Do not restart the PC yet. Many lab PCs erase new files on restart.",
             "The PC stays on.",
             "Huwag munang i-restart ang PC. Maraming lab PC ang nagbubura ng bagong files kapag nire-restart.",
             "Naka-on pa rin ang PC."),
            ("Open the Recycle Bin, right-click the file and choose Restore.",
             "The file is back in its folder.",
             "Buksan ang Recycle Bin, i-right-click ang file at piliin ang Restore.",
             "Bumalik na ang file sa folder."),
            ("Search for the file name in File Explorer and check Quick access > Recent files.",
             "You find where it was saved.",
             "I-search ang pangalan ng file sa File Explorer at tingnan ang Quick access > Recent files.",
             "Nakita kung saan ito na-save."),
            ("For Word/Excel/PowerPoint: File > Info > Manage Document > Recover Unsaved Documents.",
             "An autosaved copy appears.",
             "Para sa Word/Excel/PowerPoint: File > Info > Manage Document > Recover Unsaved Documents.",
             "May lumabas na autosaved na kopya."),
            ("If you used OneDrive or Google Drive, check its Trash or Version history.",
             "An earlier version is available.",
             "Kung gumamit ng OneDrive o Google Drive, tingnan ang Trash o Version history.",
             "May mas naunang bersyon."),
        ],
        "solution": {
            "en": "Restore from the Recycle Bin, autosave or cloud history. Always save work to a flash drive or cloud, not only on the lab PC.",
            "tl": "I-restore mula sa Recycle Bin, autosave o cloud history. Laging i-save ang gawa sa flash drive o cloud, hindi lang sa lab PC.",
        },
        "escalation": {
            "en": "Ask the technician quickly, before the PC is restarted, if the file is important and not found.",
            "tl": "Magtanong agad sa technician bago i-restart ang PC kung mahalaga ang file at hindi makita.",
        },
    },
    # --------------------------------------------------------------
    {
        "id": "windows_update",
        "category": "System",
        "priority": "Low",
        "keywords": [
            "windows update", "working on updates", "configuring updates",
            "installing updates", "don't turn off your computer",
            "do not turn off your computer", "update stuck", "stuck on update",
            "stuck updating", "restart to update", "updating windows",
            "nag-a-update ang windows", "nag update ang windows", "stuck sa update",
            "naka stuck sa update",
        ],
        "cause": {
            "en": "Windows is installing updates, which can take a while and must not be interrupted.",
            "tl": "Nag-i-install ng updates ang Windows; maaaring matagal at hindi dapat putulin.",
        },
        "steps": [
            ("Do not turn off or unplug the PC.",
             "The PC stays on.",
             "Huwag i-off o tanggalin sa saksakan ang PC.",
             "Naka-on pa rin ang PC."),
            ("Wait 30-60 minutes; use another PC in the meantime.",
             "The percentage keeps increasing.",
             "Maghintay ng 30-60 minuto; gumamit muna ng ibang PC.",
             "Tumataas ang porsyento."),
            ("If the percentage has not changed for over 2 hours, note it and report it.",
             "You have the stuck percentage and time.",
             "Kung hindi gumagalaw ang porsyento nang higit 2 oras, tandaan at i-report.",
             "Alam ang naka-stuck na porsyento at oras."),
        ],
        "solution": {
            "en": "Let updates finish. Turning the PC off mid-update can damage Windows.",
            "tl": "Hayaang matapos ang update. Maaaring masira ang Windows kapag in-off habang nag-a-update.",
        },
        "escalation": {
            "en": "Report it to the technician if it is stuck for more than 2 hours or fails repeatedly.",
            "tl": "I-report sa technician kung naka-stuck nang higit 2 oras o paulit-ulit na pumapalya.",
        },
    },
    # --------------------------------------------------------------
    {
        "id": "clock_wrong",
        "category": "System",
        "priority": "Low",
        "keywords": [
            "wrong time", "wrong date", "time is wrong", "date is wrong",
            "clock is wrong", "clock is ahead", "clock is behind",
            "your clock is ahead", "your clock is behind", "err_cert_date_invalid",
            "certificate error", "cmos", "time resets",
            "mali ang oras", "mali oras", "mali ang date", "mali ang petsa",
            "bumabalik ang oras", "sayop ang oras",
        ],
        "cause": {
            "en": "Automatic time sync is off, or the motherboard's small CMOS battery is weak so the clock resets.",
            "tl": "Naka-off ang automatic time sync, o mahina na ang maliit na CMOS battery ng motherboard kaya nagre-reset ang oras.",
        },
        "steps": [
            ("Open Settings > Time & language > Date & time, turn on 'Set time automatically', and click Sync now.",
             "The clock shows the correct time.",
             "Buksan ang Settings > Time & language > Date & time, i-on ang 'Set time automatically', at i-click ang Sync now.",
             "Tama na ang oras."),
            ("Check the time zone is (UTC+08:00) Manila.",
             "The time zone is correct.",
             "Tingnan kung (UTC+08:00) Manila ang time zone.",
             "Tama ang time zone."),
            ("Reload the website that showed a certificate or clock error.",
             "The site opens normally.",
             "I-reload ang website na nagpakita ng certificate o clock error.",
             "Normal nang bumukas ang site."),
        ],
        "solution": {
            "en": "Turn on automatic time. If the time is wrong again after every shutdown, the CMOS battery must be replaced by the technician.",
            "tl": "I-on ang automatic time. Kung mali ulit ang oras tuwing pinapatay, kailangang palitan ng technician ang CMOS battery.",
        },
        "escalation": {
            "en": "Report it if the settings are locked (needs admin rights) or the time keeps resetting.",
            "tl": "I-report kung naka-lock ang settings (kailangan ng admin) o paulit-ulit na nagre-reset ang oras.",
        },
    },
    # --------------------------------------------------------------
    {
        "id": "overheating_noise",
        "category": "Hardware",
        "priority": "High",
        "keywords": [
            "overheat", "overheating", "=hot", "very hot", "too hot", "loud fan",
            "fan noise", "noisy", "grinding noise", "clicking noise", "beep", "beeps",
            "beeping", "weird noise", "strange noise",
            "mainit", "sobrang init", "umiinit", "maingay", "ang ingay", "maingay ang fan",
            "tumutunog", "nagbe-beep", "nagbibeep", "nag beep", "kakaibang tunog",
            "init kaayo", "saba",
        ],
        "cause": {
            "en": "Blocked air vents, dust build-up, a failing fan, or (for beeps at startup) a hardware fault the PC is signalling.",
            "tl": "Natatakpang butas ng hangin, maalikabok, nasisirang fan, o (kung nagbe-beep sa pag-start) may hardware fault na sinasabi ang PC.",
        },
        "steps": [
            ("Make sure nothing blocks the vents and there's space behind and beside the PC.",
             "Air flows freely around the case.",
             "Siguraduhing walang nakaharang sa butas ng hangin at may espasyo sa likod at gilid ng PC.",
             "Malayang dumadaloy ang hangin."),
            ("Close heavy programs and let the PC rest a few minutes.",
             "The fan quiets down and the case cools.",
             "Isara ang mabibigat na program at ipahinga ang PC ng ilang minuto.",
             "Humina ang fan at lumamig ang case."),
            ("If the PC beeps when starting, count the pattern (e.g. 1 long, 2 short).",
             "You have the beep pattern.",
             "Kung nagbe-beep pag-start, bilangin ang pattern (hal. 1 mahaba, 2 maikli).",
             "Nakuha ang beep pattern."),
            ("If it is very hot, makes grinding noises, or shuts down by itself, shut it down and stop using it. Do not open the case.",
             "The PC is off.",
             "Kung sobrang init, may gumagasgas na tunog, o kusang namamatay, i-shut down at huwag nang gamitin. Huwag buksan ang case.",
             "Naka-off na ang PC."),
        ],
        "solution": {
            "en": "Improve airflow. Persistent heat, loud or grinding fans, or startup beeps need cleaning or part replacement by the technician.",
            "tl": "Ayusin ang daloy ng hangin. Kung tuloy ang init, maingay o gumagasgas na fan, o beep pag-start, kailangang linisin o palitan ng technician ang piyesa.",
        },
        "escalation": {
            "en": "Report it with the beep pattern or noise description. Stop immediately and report if you smell burning.",
            "tl": "I-report kasama ang beep pattern o paglalarawan ng tunog. Itigil agad at i-report kung may amoy sunog.",
        },
    },
]


GENERAL_ENTRY: dict = {
    "id": "general",
    "category": "Other",
    "priority": "Medium",
    "keywords": [],
    "cause": {
        "en": "Not enough details yet to identify the exact cause.",
        "tl": "Kulang pa ang detalye para matukoy ang eksaktong sanhi.",
    },
    "steps": [
        ("Save your work, then close and reopen the program you were using.",
         "The problem is gone.",
         "I-save ang ginagawa, tapos isara at buksan muli ang program na gamit.",
         "Nawala ang problema."),
        ("Restart the PC.",
         "It works normally after restarting.",
         "I-restart ang PC.",
         "Normal na pagka-restart."),
        ("Check that all cables (power, monitor, keyboard, mouse, LAN) are firmly connected.",
         "Nothing is loose.",
         "Tingnan kung mahigpit ang lahat ng cable (power, monitor, keyboard, mouse, LAN).",
         "Walang maluwag."),
        ("Write down or photograph any error message, and check if other PCs have the same problem.",
         "You know the exact message and whether it is one PC or many.",
         "Isulat o kunan ng litrato ang error message, at tingnan kung may parehong problema ang ibang PC.",
         "Alam ang eksaktong mensahe at kung isang PC o marami."),
    ],
    "solution": {
        "en": "Restarting fixes many temporary problems. Describe the problem in more detail (what you see, the error text, which PC) for a more specific answer.",
        "tl": "Maraming pansamantalang problema ang naaayos sa pag-restart. Ilarawan pa ang problema (ano ang nakikita, ang error, aling PC) para sa mas tiyak na sagot.",
    },
    "escalation": {
        "en": "Submit a report with the PC number and error message if the problem continues.",
        "tl": "Mag-submit ng report kasama ang PC number at error message kung tuloy pa rin ang problema.",
    },
}


# ============================================================
# LOADING (built-in + kb_custom.json)
# ============================================================

_LEVELS = {"low": "Low", "medium": "Medium", "high": "High"}


def _text_field(value) -> dict | None:
    """Accept "text" or {"en": ..., "tl": ...}; return {"en", "tl"} or None."""
    if isinstance(value, str) and value.strip():
        return {"en": value.strip(), "tl": value.strip()}
    if isinstance(value, dict):
        en = str(value.get("en") or "").strip()
        tl = str(value.get("tl") or "").strip()
        if en or tl:
            return {"en": en or tl, "tl": tl or en}
    return None


def _step(value) -> tuple | None:
    """Accept a list/tuple (en, check_en[, tl, check_tl]) or a dict."""
    if isinstance(value, dict):
        action = str(value.get("action") or value.get("en") or "").strip()
        if not action:
            return None
        check = str(value.get("check") or "").strip()
        action_tl = str(value.get("action_tl") or value.get("tl") or action).strip()
        check_tl = str(value.get("check_tl") or check).strip()
        return (action, check, action_tl, check_tl)
    if isinstance(value, str) and value.strip():
        return (value.strip(), "", value.strip(), "")
    if isinstance(value, (list, tuple)) and value:
        parts = [str(p).strip() for p in value]
        if len(parts) == 1:
            return (parts[0], "", parts[0], "")
        if len(parts) < 4:
            return (parts[0], parts[1], parts[0], parts[1])
        return tuple(parts[:4])
    return None


def _validate(raw) -> dict | None:
    if not isinstance(raw, dict) or not str(raw.get("id") or "").strip():
        return None

    keywords = [str(k).strip() for k in raw.get("keywords", []) if str(k).strip()]
    steps = [s for s in (_step(v) for v in raw.get("steps", [])) if s]
    cause = _text_field(raw.get("cause"))
    if not keywords or not steps or not cause:
        return None

    blank = {"en": "", "tl": ""}
    return {
        "id": str(raw["id"]).strip(),
        "category": str(raw.get("category") or "Other").strip().title(),
        "priority": _LEVELS.get(str(raw.get("priority", "")).strip().lower(), "Medium"),
        "keywords": keywords,
        "cause": cause,
        "steps": steps,
        "solution": _text_field(raw.get("solution")) or blank,
        "escalation": _text_field(raw.get("escalation")) or blank,
    }


def _load_custom() -> list:
    if not CUSTOM_KB_PATH.exists():
        return []
    try:
        data = json.loads(CUSTOM_KB_PATH.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("Could not read %s: %s", CUSTOM_KB_PATH.name, e)
        return []
    if isinstance(data, dict):
        data = data.get("entries", [])
    return data if isinstance(data, list) else []


def load_kb() -> list[dict]:
    """Built-in entries, with kb_custom.json entries added or replacing them."""
    entries: dict[str, dict] = {}
    for raw in BUILTIN_KB:
        entry = _validate(raw)
        if entry:
            entries[entry["id"]] = entry

    added = 0
    for raw in _load_custom():
        if isinstance(raw, dict) and raw.get("disabled") and raw.get("id"):
            entries.pop(str(raw["id"]).strip(), None)
            continue
        entry = _validate(raw)
        if entry is None:
            log.warning(
                "Skipped an invalid entry in %s (needs id, keywords, cause and steps): %r",
                CUSTOM_KB_PATH.name,
                (raw or {}).get("id") if isinstance(raw, dict) else raw,
            )
            continue
        entries[entry["id"]] = entry
        added += 1

    if added:
        log.info("Loaded %d custom knowledge base entries", added)
    return list(entries.values())


KB: list[dict] = load_kb()