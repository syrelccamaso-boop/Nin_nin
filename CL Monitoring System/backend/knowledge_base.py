"""
Offline knowledge base for the Centrum Laboratory troubleshooting assistant.

Each entry has:
  id, category, priority (Low/Medium/High),
  keywords  -> English, Tagalog and Taglish phrases used for matching
  cause / solution / escalation -> {"en": ..., "tl": ...}
  steps     -> list of (en_action, en_check, tl_action, tl_check)

You can ADD entries without touching this file: create `kb_custom.json`
next to it as a list of entries using the same fields, e.g.

[
  {
    "id": "projector",
    "category": "Hardware",
    "priority": "Medium",
    "keywords": ["projector", "walang display sa projector", "hdmi"],
    "cause": {"en": "...", "tl": "..."},
    "steps": [["Action", "Check", "Aksyon", "Tingnan"]],
    "solution": {"en": "...", "tl": "..."},
    "escalation": {"en": "...", "tl": "..."}
  }
]
"""

import json
from pathlib import Path

BUILTIN_KB = [
    # ------------------------------------------------------------------ POWER
    {
        "id": "no_power",
        "category": "Hardware",
        "priority": "Medium",
        "keywords": [
            "won't turn on",
            "wont turn on",
            "not turning on",
            "no power",
            "power button",
            "dead pc",
            "does not start",
            "ayaw bumukas",
            "ayaw mag on",
            "ayaw mag-on",
            "walang power",
            "patay",
            "di bumubukas",
            "hindi bumubukas",
            "hindi nag on",
            "namatay",
            "walang ilaw",
            "walang kuryente",
        ],
        "cause": {
            "en": "Usually a loose or unpowered connection (outlet, extension, power cable), or a faulty power cable/button. Internal hardware faults are rare.",
            "tl": "Kadalasan maluwag o walang kuryente ang koneksyon (outlet, extension, o power cable), o sira ang power cable/button. Bihira ang sira sa loob ng unit.",
        },
        "steps": [
            (
                "Make sure the PC and monitor power cables are fully plugged in on both ends.",
                "Are the plugs firm, and are the cables free of damage or sharp bends?",
                "Siguraduhing nakasaksak nang maayos ang power cable ng PC at monitor sa magkabilang dulo.",
                "Mahigpit ba ang saksak at walang sira o baluktot na cable?",
            ),
            (
                "Test the wall outlet or extension cord with a device that you know works (lamp, phone charger).",
                "Does the other device turn on? If not, the outlet, extension or breaker is the problem.",
                "Subukan ang outlet o extension gamit ang ibang gumaganang gamit (hal. lamp o charger).",
                "Bumukas ba ang ibang gamit? Kung hindi, ang outlet/extension/breaker ang problema.",
            ),
            (
                "Swap in a known-good power cable and try a different outlet.",
                "Do any case lights or fans respond when you press the power button?",
                "Palitan ng gumaganang power cable at subukan ang ibang outlet.",
                "May ilaw o umiikot na fan ba kapag pinindot ang power button?",
            ),
            (
                "Unplug the PC, hold the power button for 15 seconds, plug it back in and try again.",
                "Any lights, fan spin or beeps?",
                "I-unplug ang PC, pindutin nang 15 segundo ang power button, isaksak ulit at subukang buksan.",
                "May ilaw, tunog ng fan, o beep ba?",
            ),
            (
                "Disconnect USB devices and extra peripherals, then try to power on again.",
                "Does it start without them? If yes, reconnect them one at a time to find the faulty one.",
                "Tanggalin ang mga USB device at iba pang nakakabit, saka subukang buksan ulit.",
                "Bumukas ba kapag wala sila? Kung oo, isaksak isa-isa para malaman kung alin ang sira.",
            ),
        ],
        "solution": {
            "en": "Replace the faulty cable or move to a working outlet/extension. If a peripheral blocked startup, keep it disconnected and report it.",
            "tl": "Palitan ang sirang cable o lumipat sa gumaganang outlet/extension. Kung may device na pumipigil mag-start, huwag munang ikabit at i-report.",
        },
        "escalation": {
            "en": "Escalate to hardware repair if there are still no lights or fans with a confirmed good outlet and cable. Do not open the case or the power supply.",
            "tl": "I-escalate sa hardware repair kung wala pa ring ilaw o fan kahit tama ang outlet at cable. Huwag buksan ang case o ang power supply.",
        },
    },
    # ---------------------------------------------------------------- DISPLAY
    {
        "id": "no_display",
        "category": "Hardware",
        "priority": "Medium",
        "keywords": [
            "no display",
            "black screen",
            "blank screen",
            "no signal",
            "no video",
            "monitor",
            "screen is black",
            "walang display",
            "walang signal",
            "itim ang screen",
            "blangko",
            "walang lumalabas",
            "hindi nag display",
            "di nag display",
            "walang image",
            "itim na screen",
        ],
        "cause": {
            "en": "Usually a loose or wrong video cable, wrong monitor input, or the monitor is not powered. Less often a graphics output problem.",
            "tl": "Kadalasan maluwag o maling video cable, maling input ng monitor, o walang power ang monitor. Mas bihira ang problema sa graphics output.",
        },
        "steps": [
            (
                "Check the monitor's power light and press its power button.",
                "Is the LED on? Does it say 'No Signal'?",
                "Tingnan ang power light ng monitor at pindutin ang power button nito.",
                "Naka-on ba ang LED? May lumalabas bang 'No Signal'?",
            ),
            (
                "Reseat the video cable (HDMI/VGA/DisplayPort) on both the monitor and the PC. Tighten the screws on VGA.",
                "Did the picture appear or did the message change?",
                "Tanggalin at isaksak ulit ang video cable (HDMI/VGA/DisplayPort) sa monitor at PC. Higpitan ang turnilyo ng VGA.",
                "Lumabas ba ang larawan o nagbago ba ang mensahe?",
            ),
            (
                "Use the monitor's Input/Source button and select the matching input (HDMI, VGA or DP).",
                "Does the image show up on the correct input?",
                "Gamitin ang Input/Source button ng monitor at piliin ang tamang input (HDMI, VGA o DP).",
                "Lumabas ba ang image sa tamang input?",
            ),
            (
                "Try another known-good video cable, or connect the PC to another monitor.",
                "Does it display on the other cable/monitor? If yes, the original cable or monitor is faulty.",
                "Subukan ang ibang gumaganang video cable, o ikabit ang PC sa ibang monitor.",
                "Nag-display ba sa ibang cable/monitor? Kung oo, sira ang orihinal na cable o monitor.",
            ),
            (
                "Confirm the PC is really on (fans, Caps Lock light). Then press Win+Ctrl+Shift+B, or Win+P and choose 'PC screen only'.",
                "Does the screen flicker or come back?",
                "Tiyaking naka-on talaga ang PC (fan, Caps Lock light). Pindutin ang Win+Ctrl+Shift+B, o Win+P at piliin ang 'PC screen only'.",
                "Nag-flicker o bumalik ba ang screen?",
            ),
        ],
        "solution": {
            "en": "Replace the faulty cable/monitor or select the correct input source.",
            "tl": "Palitan ang sirang cable/monitor o piliin ang tamang input source.",
        },
        "escalation": {
            "en": "Escalate if the PC is on, the cable and monitor are both confirmed good, and there is still no image.",
            "tl": "I-escalate kung naka-on ang PC, tiyak na gumagana ang cable at monitor, pero wala pa ring image.",
        },
    },
    # ------------------------------------------------------------------- SLOW
    {
        "id": "slow_pc",
        "category": "System",
        "priority": "Low",
        "keywords": [
            "slow",
            "lag",
            "laggy",
            "sluggish",
            "takes forever",
            "mabagal",
            "bagal",
            "matagal mag open",
            "matagal mag-open",
            "nagla lag",
            "nagla-lag",
            "sobrang bagal",
            "mabagal ang computer",
            "mabagal ang pc",
        ],
        "cause": {
            "en": "Often too many background apps, low free disk space, pending updates, or a background scan. Sometimes malware or low RAM.",
            "tl": "Kadalasan sobrang daming background apps, kulang ang free space ng disk, may pending update, o may background scan. Minsan malware o kulang sa RAM.",
        },
        "steps": [
            (
                "Save work and restart the PC.",
                "Is it faster right after restarting?",
                "I-save ang trabaho at i-restart ang PC.",
                "Bumilis ba pagkatapos mag-restart?",
            ),
            (
                "Open Task Manager (Ctrl+Shift+Esc) and sort by CPU, Memory and Disk.",
                "Is any app constantly using more than 80%?",
                "Buksan ang Task Manager (Ctrl+Shift+Esc) at i-sort ayon sa CPU, Memory at Disk.",
                "May app ba na palaging gumagamit ng higit 80%?",
            ),
            (
                "Close unneeded apps and browser tabs. Only 'End task' apps you recognise, never system processes.",
                "Does usage drop and does the PC respond better?",
                "Isara ang mga hindi kailangang app at browser tab. 'End task' lang ang mga kilalang app, huwag ang system process.",
                "Bumaba ba ang usage at gumanda ba ang response ng PC?",
            ),
            (
                "Open This PC and check free space on drive C:. Run Disk Cleanup if space is low.",
                "Is there at least 15% free space?",
                "Buksan ang This PC at tingnan ang free space ng drive C:. Mag-run ng Disk Cleanup kung kulang.",
                "May kahit 15% na free space ba?",
            ),
            (
                "Check for running Windows updates or antivirus scans and let them finish. Then check Task Manager > Startup and disable unneeded startup apps.",
                "Does the slowness stop once updates or scans complete?",
                "Tingnan kung may tumatakbong Windows update o antivirus scan at hayaang matapos. Tingnan ang Task Manager > Startup at i-disable ang hindi kailangan.",
                "Nawala ba ang bagal pagkatapos matapos ang update o scan?",
            ),
        ],
        "solution": {
            "en": "Free disk space, disable heavy startup apps, finish updates, and run a full antivirus scan. Consider a RAM or SSD upgrade if usage stays high.",
            "tl": "Magbakante ng disk space, i-disable ang mabibigat na startup app, tapusin ang updates, at mag-full antivirus scan. Isaalang-alang ang RAM o SSD upgrade kung mataas pa rin ang usage.",
        },
        "escalation": {
            "en": "Escalate if it stays slow after cleanup, disk usage is always at 100%, or you suspect malware or a failing drive.",
            "tl": "I-escalate kung mabagal pa rin pagkatapos ng cleanup, laging 100% ang disk, o may hinala ng malware o sirang drive.",
        },
    },
    # ---------------------------------------------------------------- NETWORK
    {
        "id": "no_internet",
        "category": "Network",
        "priority": "High",
        "keywords": [
            "no internet",
            "internet",
            "wifi",
            "wi fi",
            "network",
            "ethernet",
            "lan",
            "cannot connect",
            "can't connect",
            "cant connect",
            "disconnected",
            "limited",
            "walang internet",
            "walang connection",
            "walang net",
            "di maka connect",
            "hindi maka connect",
            "mabagal ang internet",
            "nawala ang internet",
            "walang koneksyon",
            "offline",
        ],
        "cause": {
            "en": "Could be a loose cable or dead port, a disabled adapter, a bad IP/DNS configuration, or an upstream switch/router/ISP problem.",
            "tl": "Maaaring maluwag na cable o sirang port, naka-disable na adapter, maling IP/DNS, o problema sa switch/router/ISP.",
        },
        "steps": [
            (
                "Check that the Ethernet cable is firmly plugged in and the port lights blink, or that Wi-Fi is on and Airplane mode is off.",
                "Does the network icon show connected, or a red X / globe?",
                "Tiyaking nakasaksak nang maayos ang Ethernet cable at kumikislap ang ilaw ng port, o naka-on ang Wi-Fi at naka-off ang Airplane mode.",
                "Connected ba ang network icon, o may red X / globe?",
            ),
            (
                "Test whether other PCs in the lab have internet.",
                "If all are down, it is a network-wide problem, so escalate. If only this PC, continue.",
                "Subukan kung may internet ang ibang PC sa lab.",
                "Kung lahat ay walang internet, network-wide ito kaya i-escalate. Kung isang PC lang, magpatuloy.",
            ),
            (
                "Disable and re-enable the network adapter (Settings > Network & Internet > Advanced network settings), or reconnect to Wi-Fi.",
                "Does the icon change to connected?",
                "I-disable at i-enable ulit ang network adapter (Settings > Network & Internet > Advanced network settings), o mag-reconnect sa Wi-Fi.",
                "Naging connected ba ang icon?",
            ),
            (
                "Open Command Prompt and run: ipconfig /release then ipconfig /renew.",
                "Does it get a valid IP address (not 169.254.x.x)?",
                "Buksan ang Command Prompt at i-run: ipconfig /release tapos ipconfig /renew.",
                "Nakakuha ba ng valid na IP address (hindi 169.254.x.x)?",
            ),
            (
                "Run: ping 8.8.8.8, then ping google.com. If only the name fails, run ipconfig /flushdns.",
                "IP works but name fails = DNS issue. Both fail = no connection to the network or internet.",
                "I-run: ping 8.8.8.8, tapos ping google.com. Kung pangalan lang ang pumapalya, i-run ang ipconfig /flushdns.",
                "Gumagana ang IP pero hindi ang pangalan = DNS issue. Parehong pumalya = walang koneksyon sa network o internet.",
            ),
            (
                "Try a different Ethernet cable or wall port.",
                "Does the link come up on the new cable or port?",
                "Subukan ang ibang Ethernet cable o wall port.",
                "Nag-connect ba sa bagong cable o port?",
            ),
        ],
        "solution": {
            "en": "Replace the bad cable/port, renew the IP address or flush DNS as needed.",
            "tl": "Palitan ang sirang cable/port, i-renew ang IP address o i-flush ang DNS kung kailangan.",
        },
        "escalation": {
            "en": "Escalate to the network admin if several PCs are down, the PC keeps a 169.254.x.x address, or the switch/router/ISP is suspected.",
            "tl": "I-escalate sa network admin kung maraming PC ang apektado, 169.254.x.x ang IP, o may hinala sa switch/router/ISP.",
        },
    },
    # ------------------------------------------------------------------ LOGIN
    {
        "id": "login_issue",
        "category": "System",
        "priority": "Medium",
        "keywords": [
            "can't log in",
            "cant log in",
            "cannot login",
            "cannot log in",
            "login",
            "log in",
            "password",
            "account locked",
            "wrong password",
            "user profile",
            "temporary profile",
            "di maka login",
            "hindi maka login",
            "nakalimutan ang password",
            "naka lock",
            "nakalock",
            "maling password",
            "ayaw mag login",
            "ayaw mag-login",
            "forgot password",
        ],
        "cause": {
            "en": "Often a typing/keyboard-layout error, locked or expired account, no network connection to the login server, or a corrupted user profile.",
            "tl": "Kadalasan maling type o keyboard layout, naka-lock o expired na account, walang koneksyon sa login server, o sira ang user profile.",
        },
        "steps": [
            (
                "Check Caps Lock/Num Lock and the keyboard language (ENG/FIL). Retype slowly using the 'show password' eye icon.",
                "Is the typed password what the user intended?",
                "Tingnan ang Caps Lock/Num Lock at ang keyboard language (ENG/FIL). I-type nang dahan-dahan gamit ang 'show password' na eye icon.",
                "Tama ba ang na-type na password?",
            ),
            (
                "Confirm the exact username/domain format used by the lab (for example, ID number versus email).",
                "Does the format match what the lab uses?",
                "Kumpirmahin ang eksaktong format ng username/domain ng lab (hal. ID number o email).",
                "Tugma ba ang format sa ginagamit ng lab?",
            ),
            (
                "If the lab uses a server/domain login, verify the PC is connected to the network.",
                "Is the network icon connected?",
                "Kung server/domain login ang gamit, tiyaking konektado ang PC sa network.",
                "Connected ba ang network icon?",
            ),
            (
                "Read the error message carefully. Do not keep guessing passwords because that can lock the account.",
                "Does it say locked, disabled, expired, or 'temporary profile'?",
                "Basahin nang mabuti ang error message. Huwag paulit-ulit manghula ng password dahil maaaring ma-lock ang account.",
                "Sinasabi bang locked, disabled, expired, o 'temporary profile'?",
            ),
            (
                "Restart the PC and try again, or try the same account on another PC.",
                "Works elsewhere = problem is this PC/profile. Fails everywhere = account problem.",
                "I-restart ang PC at subukan ulit, o subukan ang parehong account sa ibang PC.",
                "Gumana sa iba = problema ng PC/profile na ito. Pumalya kahit saan = problema ng account.",
            ),
        ],
        "solution": {
            "en": "Have the admin unlock or reset the account, or rebuild the user profile. Never share or write down a user's password.",
            "tl": "Ipa-unlock o ipa-reset sa admin ang account, o ipa-rebuild ang user profile. Huwag ibahagi o isulat ang password ng user.",
        },
        "escalation": {
            "en": "Escalate to the system admin for locked or expired accounts, password resets, or a corrupted or temporary profile.",
            "tl": "I-escalate sa system admin para sa naka-lock o expired na account, password reset, o sira/temporary na profile.",
        },
    },
    # ---------------------------------------------------------------- PRINTER
    {
        "id": "printer",
        "category": "Hardware",
        "priority": "Low",
        "keywords": [
            "printer",
            "print",
            "printing",
            "paper jam",
            "toner",
            "ink",
            "spooler",
            "di nagpi print",
            "hindi nagpi print",
            "ayaw mag print",
            "ayaw mag-print",
            "walang lumalabas na print",
            "naipit",
            "nakapila",
            "offline ang printer",
        ],
        "cause": {
            "en": "Commonly an out-of-paper/ink condition, a paper jam, a stuck print queue, the printer set to offline, or a loose cable/network link.",
            "tl": "Karaniwang kulang sa papel/tinta, paper jam, nakabara ang print queue, naka-offline ang printer, o maluwag ang cable/network.",
        },
        "steps": [
            (
                "Check printer power, paper, ink/toner and any error lights or display messages.",
                "Are there blinking lights or error messages?",
                "Tingnan ang power ng printer, papel, tinta/toner at anumang error light o mensahe sa display.",
                "May kumikislap na ilaw o error message ba?",
            ),
            (
                "If there is a paper jam, switch the printer off and gently remove the paper following the printer manual.",
                "Are all paper pieces removed with nothing torn inside?",
                "Kung may paper jam, patayin ang printer at dahan-dahang alisin ang papel ayon sa manual.",
                "Naalis ba lahat ng papel at walang napunit sa loob?",
            ),
            (
                "Check the USB or network connection and that the printer shows Ready/Online.",
                "Is the printer reachable and showing Ready?",
                "Tingnan ang USB o network connection at kung 'Ready/Online' ang printer.",
                "Naaabot ba ang printer at 'Ready' ang status?",
            ),
            (
                "On the PC open Settings > Printers & scanners > your printer > Open print queue. Cancel stuck jobs and make sure 'Use Printer Offline' is unchecked.",
                "Is the queue empty and the status Ready?",
                "Sa PC, buksan ang Settings > Printers & scanners > ang printer > Open print queue. I-cancel ang mga nakabarang job at siguraduhing naka-uncheck ang 'Use Printer Offline'.",
                "Walang laman ang queue at 'Ready' ba ang status?",
            ),
            (
                "Restart the printer and the PC, then print a test page.",
                "Does the test page print?",
                "I-restart ang printer at PC, saka mag-print ng test page.",
                "Nag-print ba ang test page?",
            ),
        ],
        "solution": {
            "en": "Clear the jam or stuck queue, set the correct default printer, or reinstall the driver.",
            "tl": "Alisin ang jam o nakabarang queue, itakda ang tamang default printer, o i-reinstall ang driver.",
        },
        "escalation": {
            "en": "Escalate for repeated jams, streaks, grinding noises, or when cartridges or the fuser need replacement.",
            "tl": "I-escalate kung paulit-ulit ang jam, may guhit sa print, may kakaibang ingay, o kailangang palitan ang cartridge o fuser.",
        },
    },
    # ------------------------------------------------------------ PERIPHERALS
    {
        "id": "peripherals",
        "category": "Hardware",
        "priority": "Low",
        "keywords": [
            "keyboard",
            "mouse",
            "usb",
            "flash drive",
            "not detected",
            "not recognized",
            "cursor",
            "ayaw gumana ang mouse",
            "ayaw gumana ang keyboard",
            "sira ang mouse",
            "sira ang keyboard",
            "di ma detect",
            "hindi ma detect",
            "usb port",
            "di nababasa",
            "hindi nababasa",
            "walang response",
            "hindi gumagalaw ang cursor",
        ],
        "cause": {
            "en": "Usually a loose connection, a dead USB port, low batteries or receiver problems (wireless), or a driver glitch.",
            "tl": "Kadalasan maluwag ang koneksyon, sirang USB port, mahina ang baterya o problema sa receiver (wireless), o glitch sa driver.",
        },
        "steps": [
            (
                "Unplug the device and plug it back firmly into the same port.",
                "Does Windows make a connect sound or does the device light up?",
                "I-unplug ang device at isaksak ulit nang mahigpit sa parehong port.",
                "May tunog ng connect ba ang Windows o umiilaw ba ang device?",
            ),
            (
                "Try a different USB port (use the back ports on a desktop).",
                "Does it work on another port?",
                "Subukan ang ibang USB port (gamitin ang mga port sa likod ng desktop).",
                "Gumana ba sa ibang port?",
            ),
            (
                "Test the device on another PC, or test a known-good device on this PC.",
                "Works elsewhere = the device is fine and the PC port/driver is suspect. Fails elsewhere = the device is faulty.",
                "Subukan ang device sa ibang PC, o subukan ang gumaganang device sa PC na ito.",
                "Gumana sa iba = ayos ang device at ang port/driver ng PC ang suspek. Pumalya = sira ang device.",
            ),
            (
                "For wireless devices, check the batteries and the USB receiver. Then restart the PC.",
                "Does the device work after fresh batteries or a restart?",
                "Para sa wireless, tingnan ang baterya at USB receiver. Pagkatapos ay i-restart ang PC.",
                "Gumana ba pagkatapos ng bagong baterya o restart?",
            ),
            (
                "Open Device Manager (Win+X). Look for a yellow warning, right-click the device > Uninstall device, then choose Action > Scan for hardware changes.",
                "Does the device reinstall and work?",
                "Buksan ang Device Manager (Win+X). Hanapin ang yellow warning, right-click ang device > Uninstall device, tapos Action > Scan for hardware changes.",
                "Na-reinstall ba ang device at gumana?",
            ),
        ],
        "solution": {
            "en": "Replace the faulty device or use a working port. Reinstall the driver if it was a driver glitch.",
            "tl": "Palitan ang sirang device o gumamit ng gumaganang port. I-reinstall ang driver kung glitch ito.",
        },
        "escalation": {
            "en": "Escalate if several USB ports are dead or the device works nowhere after the steps above.",
            "tl": "I-escalate kung maraming USB port ang hindi gumagana o hindi gumagana ang device kahit saan matapos ang mga hakbang.",
        },
    },
    # ---------------------------------------------------------- CRASH / FREEZE
    {
        "id": "crash_freeze",
        "category": "Software",
        "priority": "Medium",
        "keywords": [
            "freeze",
            "frozen",
            "not responding",
            "hang",
            "hanging",
            "crash",
            "crashes",
            "blue screen",
            "bsod",
            "restarts by itself",
            "keeps restarting",
            "stopped working",
            "error message",
            "nag freeze",
            "nag-freeze",
            "nag hang",
            "nag-hang",
            "hindi tumutugon",
            "biglang nag restart",
            "biglang namatay",
            "nag crash",
            "ayaw mag open",
            "ayaw mag-open",
            "hindi bumubukas ang program",
            "may error",
            "asul na screen",
        ],
        "cause": {
            "en": "Commonly a misbehaving program, pending updates, a bad driver, overheating, or failing RAM/disk if it happens repeatedly.",
            "tl": "Karaniwang may sumpong na program, pending update, sirang driver, overheating, o bumibigay na RAM/disk kung paulit-ulit.",
        },
        "steps": [
            (
                "Write down or photograph the exact error message or stop code (for example CRITICAL_PROCESS_DIED) and the app name.",
                "Do you have the exact wording recorded?",
                "Isulat o kunan ng litrato ang eksaktong error message o stop code (hal. CRITICAL_PROCESS_DIED) at pangalan ng app.",
                "Naitala mo ba ang eksaktong teksto?",
            ),
            (
                "Wait 1 to 2 minutes. If one app is not responding, press Ctrl+Shift+Esc and 'End task' for that app only.",
                "Does the PC recover once the app is closed?",
                "Maghintay ng 1 hanggang 2 minuto. Kung isang app lang ang hindi tumutugon, pindutin ang Ctrl+Shift+Esc at 'End task' sa app na iyon lang.",
                "Bumalik ba sa normal ang PC pagkatapos isara ang app?",
            ),
            (
                "Restart the PC and open the program again.",
                "Does it happen again, and only in one program or in all of them?",
                "I-restart ang PC at buksan ulit ang program.",
                "Nangyari ba ulit, at sa isang program lang o sa lahat?",
            ),
            (
                "Check Windows Update. Repair or reinstall the problem program (Settings > Apps > Installed apps > Modify/Repair).",
                "Does the program run after the update or repair?",
                "Tingnan ang Windows Update. I-repair o i-reinstall ang problemang program (Settings > Apps > Installed apps > Modify/Repair).",
                "Gumana ba ang program pagkatapos ng update o repair?",
            ),
            (
                "Disconnect newly attached USB devices and check for overheating: hot case, loud fans or blocked vents.",
                "Does the problem stop without the device, and are the vents clear and the case not hot?",
                "Tanggalin ang mga bagong ikinabit na USB device at tingnan kung overheating: mainit ang case, malakas ang fan o barado ang bentilasyon.",
                "Tumigil ba ang problema nang wala ang device, at malinis ba ang bentilasyon at hindi mainit ang case?",
            ),
        ],
        "solution": {
            "en": "Update or repair the problem software, remove the faulty device or driver, and clear blocked vents.",
            "tl": "I-update o i-repair ang problemang software, alisin ang sirang device o driver, at linisin ang barado na bentilasyon.",
        },
        "escalation": {
            "en": "Escalate for repeated blue screens, random restarts, or if disk or RAM failure is suspected. Bring the recorded error text.",
            "tl": "I-escalate kung paulit-ulit ang blue screen, random restart, o may hinala ng sirang disk o RAM. Dalhin ang naitalang error text.",
        },
    },
    # ------------------------------------------------------------------ SOUND
    {
        "id": "no_sound",
        "category": "Hardware",
        "priority": "Low",
        "keywords": [
            "no sound",
            "audio",
            "speaker",
            "speakers",
            "volume",
            "headset",
            "headphones",
            "microphone",
            "mic",
            "walang tunog",
            "walang sound",
            "di marinig",
            "hindi marinig",
            "walang boses",
            "ayaw mag sound",
            "ayaw mag-sound",
        ],
        "cause": {
            "en": "Usually muted volume, wrong output device, a loose audio jack, or an unpowered speaker. Occasionally a driver issue.",
            "tl": "Kadalasan naka-mute, maling output device, maluwag na audio jack, o walang power ang speaker. Paminsan-minsan driver issue.",
        },
        "steps": [
            (
                "Check the volume and mute in the taskbar, and the speaker's own power and volume knob.",
                "Is the volume up, unmuted, and the speaker powered on?",
                "Tingnan ang volume at mute sa taskbar, at ang power at volume knob ng speaker.",
                "Malakas ba, hindi naka-mute, at naka-on ang speaker?",
            ),
            (
                "Check the plug is in the right jack (green is output, pink is microphone) or the USB port.",
                "Is the plug seated firmly in the correct jack?",
                "Tiyaking tama ang jack na pinagsasaksakan (green ay output, pink ay mic) o ang USB port.",
                "Mahigpit ba ang saksak sa tamang jack?",
            ),
            (
                "Right-click the speaker icon > Sound settings and choose the correct output device.",
                "Does the volume bar move when audio plays?",
                "Right-click ang speaker icon > Sound settings at piliin ang tamang output device.",
                "Gumagalaw ba ang volume bar kapag may tunog?",
            ),
            (
                "Play the Windows test sound, or try another app or website.",
                "Is there sound in any app?",
                "I-play ang Windows test sound, o subukan ang ibang app o website.",
                "May tunog ba sa kahit anong app?",
            ),
            (
                "Restart the PC. If still silent, open Device Manager > Sound, video and game controllers and update or reinstall the audio driver.",
                "Is the audio device listed with no yellow warning?",
                "I-restart ang PC. Kung wala pa ring tunog, buksan ang Device Manager > Sound, video and game controllers at i-update o i-reinstall ang audio driver.",
                "Nakalista ba ang audio device at walang yellow warning?",
            ),
        ],
        "solution": {
            "en": "Select the correct output device, fix the connection, or reinstall the audio driver.",
            "tl": "Piliin ang tamang output device, ayusin ang koneksyon, o i-reinstall ang audio driver.",
        },
        "escalation": {
            "en": "Escalate if no audio device appears in Device Manager or the speaker/headset fails on another PC.",
            "tl": "I-escalate kung walang audio device sa Device Manager o pumapalya ang speaker/headset sa ibang PC.",
        },
    },
]

# Used when nothing in the knowledge base matches (offline general triage).
GENERAL_ENTRY = {
    "id": "general",
    "category": "Other",
    "priority": "Medium",
    "keywords": [],
    "cause": {
        "en": "The description is not specific enough to pinpoint a cause. Start with the common basics: connections, restart, and what changed recently.",
        "tl": "Hindi pa sapat ang detalye para matukoy ang sanhi. Magsimula sa mga karaniwang basic: koneksyon, restart, at kung ano ang nagbago kamakailan.",
    },
    "steps": [
        (
            "Write down exactly what is wrong, when it started, and any error message.",
            "Can you describe the symptom in one clear sentence?",
            "Isulat kung ano mismo ang problema, kailan nagsimula, at anumang error message.",
            "Kaya mo bang ilarawan ang sintomas sa isang malinaw na pangungusap?",
        ),
        (
            "Check that all cables (power, video, network, USB) are firmly connected.",
            "Is every plug seated firmly with no damaged cable?",
            "Tiyaking mahigpit ang lahat ng cable (power, video, network, USB).",
            "Mahigpit ba ang bawat saksak at walang sirang cable?",
        ),
        (
            "Save work and restart the PC.",
            "Is the problem still there after the restart?",
            "I-save ang trabaho at i-restart ang PC.",
            "Nandiyan pa rin ba ang problema pagkatapos mag-restart?",
        ),
        (
            "Ask what changed recently (new software, update, moved cables, new device) and undo it if safe.",
            "Did the problem start right after a specific change?",
            "Alamin kung ano ang nagbago kamakailan (bagong software, update, nilipat na cable, bagong device) at i-undo kung ligtas.",
            "Nagsimula ba ang problema pagkatapos ng partikular na pagbabago?",
        ),
        (
            "Try the same task on another lab PC.",
            "Same problem elsewhere = account/network/software issue. Only here = this PC.",
            "Subukan ang parehong gawain sa ibang PC sa lab.",
            "Pareho sa iba = account/network/software issue. Dito lang = problema ng PC na ito.",
        ),
    ],
    "solution": {
        "en": "Apply the fix for whichever cause the checks above point to. Record what worked.",
        "tl": "Ilapat ang ayos para sa sanhi na itinuro ng mga check sa itaas. Itala kung ano ang gumana.",
    },
    "escalation": {
        "en": "Escalate if the cause cannot be found after these steps, or if there is any smell of burning, smoke, or sparks (power off and unplug only if safe).",
        "tl": "I-escalate kung hindi pa rin matukoy ang sanhi, o kung may amoy ng sunog, usok, o spark (patayin at i-unplug lamang kung ligtas).",
    },
}


def load_kb(custom_path: str = "kb_custom.json") -> list:
    """Built-in entries plus any entries from kb_custom.json (if present)."""
    kb = list(BUILTIN_KB)
    path = Path(__file__).with_name(custom_path)
    if path.exists():
        try:
            extra = json.loads(path.read_text(encoding="utf-8"))
            for e in extra:
                e.setdefault("priority", "Medium")
                e.setdefault("category", "Other")
                e["steps"] = [tuple(s) for s in e["steps"]]
                kb.append(e)
        except Exception as exc:  # a bad custom file must never break the bot
            print(f"[KB] Could not load {custom_path}: {exc}")
    return kb


KB = load_kb()
