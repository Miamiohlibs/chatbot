"""
Shared look-and-feel for every operator surface.

Why this exists (operator feedback 2026-07-28: "the dashboard isn't
visually clear and the ticket handoffs are muddled"): the five admin
pages had grown five independent stylesheets and five different ways of
showing state, so nothing looked like part of one tool and there was no
way to tell at a glance what needed attention. This module owns:

  * one stylesheet (Miami red, cards, status pills, action buttons)
  * `page()` -- the shell every surface renders into, including a nav
    bar so you can move between queues without bouncing off the hub
  * `pill()` / `stat_card()` / `action()` -- the shared vocabulary for
    "what state is this in" and "what can I do about it"

Everything here is a pure string function: no I/O, no framework
imports, trivially unit-testable.
"""

from __future__ import annotations

import html
from typing import Optional

from src.api.admin.sso import ROLE_LIBRARIAN, ROLE_OPERATOR


def e(v: object) -> str:
    """HTML-escape anything. All admin content is untrusted: ticket text
    and conversation transcripts quote patron input."""
    return html.escape("" if v is None else str(v))


# Miami University red is the anchor; everything else is neutral so the
# status colors are the only things competing for attention.
STYLE = """
/* ---------------------------------------------------------------------
   Tokens.

   Every colour on every operator surface resolves through this block.
   It is not tidiness: the console had five hardcoded greys, three blues
   and two different "warning" reds scattered through the components
   below, which is why nothing looked like part of one tool and why the
   page could not follow a reader into dark mode.

   HSL triplets rather than hex so a component can take a colour at
   partial strength -- hsl(var(--primary) / .12) for a tint -- without a
   second token existing for every tint.

   The neutral is warm (hue 20) rather than the usual blue-grey. Beside
   Miami red a cool grey reads as two unrelated decisions; this one reads
   as the same family desaturated, which is what lets the red be the only
   thing on the page competing for attention.
   --------------------------------------------------------------------- */
:root{
  --background:0 0% 100%;
  --foreground:20 14% 12%;
  --card:0 0% 100%;
  --muted:24 16% 96%;
  --muted-foreground:20 8% 44%;
  --border:22 13% 89%;
  --input:22 13% 84%;
  --sidebar:24 16% 98%;
  --sidebar-border:22 13% 91%;
  --accent:24 16% 94%;

  /* Miami red. The one saturated colour, spent on the brand mark, the
     active nav item and primary buttons -- nowhere else. */
  --primary:354 72% 42%;
  --primary-foreground:0 0% 100%;
  --ring:354 72% 42%;
  /* The red WHEN IT IS TEXT rather than a fill. One token was doing both
     jobs and the two want opposite things: white sitting on the red wants
     it dark, the red sitting on the page wants it light. On white they
     happen to agree, so this is the same value here and splits in dark. */
  --primary-ink:354 72% 42%;

  /* Semantic, and deliberately NOT the accent: "this needs you" must not
     be the same colour as "this is a button". */
  --success:142 64% 26%;   --success-bg:142 52% 94%;
  --warning:32 84% 32%;    --warning-bg:38 92% 92%;
  --info:221 78% 42%;      --info-bg:214 95% 94%;
  --danger:0 68% 44%;      --danger-bg:0 86% 96%;

  --radius:.65rem;
}

/* THE DARK PALETTE, WRITTEN ONCE.
   Three states, not two: an explicit choice stamps data-theme on the
   root, and the default "follow my system" setting stamps nothing. A
   media query alone cannot serve a reader who has chosen dark on a
   light machine, which is exactly what the toggle does. */
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --background:20 14% 7%;
    --foreground:24 12% 94%;
    --card:20 12% 10%;
    --muted:20 10% 15%;
    --muted-foreground:22 9% 62%;
    --border:20 10% 19%;
    --input:20 10% 26%;
    --sidebar:20 13% 9%;
    --sidebar-border:20 10% 17%;
    --accent:20 10% 17%;
    
    --primary:354 58% 40%;
    --primary-foreground:0 0% 100%;
    --ring:354 45% 58%;
    --primary-ink:354 42% 66%;
    
    --success:142 55% 62%;   --success-bg:142 40% 14%;
    --warning:38 82% 62%;    --warning-bg:34 55% 14%;
    --info:214 88% 70%;      --info-bg:217 60% 15%;
    --danger:0 78% 68%;      --danger-bg:0 50% 15%;
  }
}
:root[data-theme="dark"]{
  --background:20 14% 7%;
  --foreground:24 12% 94%;
  --card:20 12% 10%;
  --muted:20 10% 15%;
  --muted-foreground:22 9% 62%;
  --border:20 10% 19%;
  --input:20 10% 26%;
  --sidebar:20 13% 9%;
  --sidebar-border:20 10% 17%;
  --accent:20 10% 17%;
  
  --primary:354 58% 40%;
  --primary-foreground:0 0% 100%;
  --ring:354 45% 58%;
  --primary-ink:354 42% 66%;
  
  --success:142 55% 62%;   --success-bg:142 40% 14%;
  --warning:38 82% 62%;    --warning-bg:34 55% 14%;
  --info:214 88% 70%;      --info-bg:217 60% 15%;
  --danger:0 78% 68%;      --danger-bg:0 50% 15%;
}

*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0;
  background:hsl(var(--background));
  color:hsl(var(--foreground));
  font:15px/1.55 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",
       system-ui,"Helvetica Neue",sans-serif;
  -webkit-font-smoothing:antialiased;
}
a{color:hsl(var(--primary-ink));text-underline-offset:2px}
a:hover{text-decoration:underline}

/* One visible focus treatment for the whole console. An operator working
   a queue from the keyboard must always be able to see where they are. */
:focus-visible{
  outline:2px solid hsl(var(--ring));
  outline-offset:2px;
  border-radius:4px;
}

/* ---------------------------------------------------------------------
   Shell: a fixed sidebar and a scrolling content column.

   The tab strip this replaces put eight destinations in one horizontal
   row with no grouping, so "where am I" and "what else is there" were
   both answered by reading eight words of the same size. A column has
   room to say which of them are queues and which are controls.
   --------------------------------------------------------------------- */
.shell{display:grid;grid-template-columns:248px minmax(0,1fr);min-height:100vh}

.sidebar{
  background:hsl(var(--sidebar));
  border-right:1px solid hsl(var(--sidebar-border));
  padding:1rem .75rem 1.5rem;
  display:flex;flex-direction:column;gap:.25rem;
  position:sticky;top:0;height:100vh;overflow-y:auto;
}
.brand{display:flex;align-items:center;gap:.55rem;padding:.35rem .5rem 1rem;
  text-decoration:none;color:inherit}
.brand:hover{text-decoration:none}
.brand .mark,.topbar .mark{
  width:1.85rem;height:1.85rem;border-radius:.5rem;flex:0 0 auto;
  background:hsl(var(--primary));color:hsl(var(--primary-foreground));
  display:grid;place-items:center;font-weight:700;font-size:.9rem;
  letter-spacing:-.02em;
}
.brand .name,.topbar .name{font-weight:600;letter-spacing:-.01em;line-height:1.15}
.brand .role,.topbar .role{display:block;font-weight:500;font-size:.72rem;
  color:hsl(var(--muted-foreground));letter-spacing:.02em}

.navgroup{margin-top:.85rem}
.navgroup > .lbl{
  padding:0 .5rem .35rem;font-size:.7rem;font-weight:600;
  text-transform:uppercase;letter-spacing:.06em;
  color:hsl(var(--muted-foreground));
}
.sidebar a.item{
  display:flex;align-items:center;gap:.55rem;
  padding:.45rem .5rem;border-radius:calc(var(--radius) - .2rem);
  text-decoration:none;color:hsl(var(--foreground));
  font-size:.9rem;font-weight:500;line-height:1.3;
}
.sidebar a.item:hover{background:hsl(var(--accent));text-decoration:none}
.sidebar a.item.on{
  background:hsl(var(--primary) / .1);
  color:hsl(var(--primary-ink));font-weight:600;
}
.sidebar a.item .ico{
  flex:0 0 1rem;width:1rem;text-align:center;opacity:.75;font-size:.95rem;
}
.sidebar a.item.on .ico{opacity:1}
.sidebar .badge{
  margin-left:auto;min-width:1.35rem;padding:.05rem .35rem;
  border-radius:999px;background:hsl(var(--danger) / .14);
  color:hsl(var(--danger));font-size:.72rem;font-weight:700;
  text-align:center;font-variant-numeric:tabular-nums;
}
/* Light / dark. Two icons, one shown at a time -- and the one shown is the
   state you are IN, not the one the button would take you to. "Which does
   this button mean?" is the entire confusion with these. */
.themetoggle{
  display:flex;align-items:center;gap:.55rem;width:100%;
  margin-top:.6rem;padding:.45rem .5rem;height:auto;
  border:1px solid transparent;border-radius:calc(var(--radius) - .2rem);
  background:transparent;color:hsl(var(--muted-foreground));
  font:inherit;font-size:.85rem;font-weight:500;cursor:pointer;
}
.themetoggle:hover{background:hsl(var(--accent));
  color:hsl(var(--foreground))}
.themetoggle .ico{flex:0 0 1rem;opacity:.8}
.themetoggle .moon{display:none}
:root[data-theme="dark"] .themetoggle .sun{display:none}
:root[data-theme="dark"] .themetoggle .moon{display:inline}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]) .themetoggle .sun{display:none}
  :root:not([data-theme="light"]) .themetoggle .moon{display:inline}
}
.topbar .themetoggle{width:auto;margin:0 0 0 auto}
/* No script, no button. It would be a control that does nothing. */
.themetoggle[hidden]{display:none}

.sidebar .foot{
  margin-top:auto;padding:.85rem .5rem 0;
  border-top:1px solid hsl(var(--sidebar-border));
  font-size:.78rem;color:hsl(var(--muted-foreground));
}
.sidebar .foot .who{display:block;color:hsl(var(--foreground));
  font-weight:500;word-break:break-all}

main{padding:1.75rem 2rem 4rem;max-width:1180px;min-width:0}

/* Pages shared outside the group -- the report form reaches any member of
   library staff who has the link. They get the visual language and no nav,
   because every destination in that nav would be a door they cannot open,
   and a menu of locked doors is worse than no menu. */
.topbar{background:hsl(var(--sidebar));
  border-bottom:1px solid hsl(var(--sidebar-border));padding:.7rem 1rem}
.topbar .wrap{max-width:820px;margin:0 auto;display:flex;align-items:center;
  gap:.55rem}
body.plain main{max-width:820px;margin:0 auto}

@media (max-width:900px){
  .shell{grid-template-columns:minmax(0,1fr)}
  .sidebar{
    position:static;height:auto;flex-direction:row;flex-wrap:nowrap;
    align-items:center;gap:.15rem;overflow-x:auto;padding:.5rem .75rem;
    border-right:0;border-bottom:1px solid hsl(var(--sidebar-border));
  }
  .brand{padding:0 .75rem 0 .25rem}
  .brand .role{display:none}
  .navgroup{margin:0;display:contents}
  .navgroup > .lbl{display:none}
  .sidebar a.item{white-space:nowrap}
  .sidebar .foot{display:none}
  .themetoggle{width:auto;margin:0 0 0 auto}
  .themetoggle span{display:none}
  main{padding:1.25rem 1rem 3rem}
}

/* --- page heading ---------------------------------------------------- */
h1{font-size:1.5rem;font-weight:600;letter-spacing:-.02em;margin:0 0 .35rem;
  line-height:1.2;text-wrap:balance}
h2{font-size:1.05rem;font-weight:600;letter-spacing:-.01em;
  margin:2rem 0 .7rem;color:hsl(var(--foreground))}
h3{font-size:.95rem;font-weight:600;margin:1.4rem 0 .5rem}
p.lede{color:hsl(var(--muted-foreground));margin:0 0 1.5rem;max-width:68ch}
p.sub{color:hsl(var(--muted-foreground));font-size:.88rem;
  margin:-.35rem 0 .8rem;max-width:68ch}
.hint{color:hsl(var(--muted-foreground));font-size:.86rem}
small.dim,.dim{color:hsl(var(--muted-foreground))}

/* --- service banner: the only question during an incident ------------- */
.banner{border-radius:var(--radius);padding:1rem 1.15rem;margin:0 0 1.4rem;
  border:1px solid hsl(var(--border))}
.banner.down{background:hsl(var(--danger-bg));
  border-color:hsl(var(--danger) / .45)}
.banner.down b{color:hsl(var(--danger));display:block;font-size:1.05rem;
  margin-bottom:.2rem}

/* --- stat tiles ------------------------------------------------------- */
.stats{display:grid;gap:.75rem;margin-bottom:1.75rem;
  grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}
.stat{
  background:hsl(var(--card));border:1px solid hsl(var(--border));
  border-radius:var(--radius);padding:1rem 1.1rem;
  text-decoration:none;color:inherit;display:block;
  transition:border-color .12s,background .12s;
}
.stat:hover{border-color:hsl(var(--foreground) / .22);text-decoration:none}
/* Label first, number second. The number is the answer; the label is the
   question, and a reader who meets the answer first has to look back up. */
.stat .lbl{color:hsl(var(--muted-foreground));font-size:.78rem;
  font-weight:500;text-transform:uppercase;letter-spacing:.05em;
  margin-bottom:.3rem;order:1}
.stat .n{font-size:1.85rem;font-weight:650;line-height:1.05;
  letter-spacing:-.03em;font-variant-numeric:tabular-nums}
.stat.needs .n{color:hsl(var(--danger))}
.stat.needs{border-color:hsl(var(--danger) / .4);
  background:hsl(var(--danger-bg) / .55)}
.stat.calm .n{color:hsl(var(--foreground))}

/* --- cards ------------------------------------------------------------ */
.card{
  background:hsl(var(--card));border:1px solid hsl(var(--border));
  border-radius:var(--radius);padding:1.1rem 1.2rem;margin-bottom:.75rem;
}
.card.attn{border-color:hsl(var(--danger) / .4)}
.card > h2:first-child{margin-top:0}
.card .meta{color:hsl(var(--muted-foreground));font-size:.8rem;
  display:flex;gap:.55rem;flex-wrap:wrap;align-items:center;
  margin-bottom:.5rem}
.card .q{font-weight:600;margin:.3rem 0;letter-spacing:-.005em}
.card .body{white-space:pre-wrap}
.card dl{margin:.5rem 0 0;display:grid;grid-template-columns:auto 1fr;
  gap:.3rem .8rem}
.card dt{color:hsl(var(--muted-foreground));font-size:.76rem;
  text-transform:uppercase;letter-spacing:.05em;font-weight:600;
  padding-top:.1rem}
.card dd{margin:0}

/* --- status pills ----------------------------------------------------- */
.pill{display:inline-block;padding:.12rem .55rem;border-radius:999px;
  font-size:.76rem;font-weight:600;white-space:nowrap;
  border:1px solid transparent}
.pill.open{background:hsl(var(--warning-bg));color:hsl(var(--warning));
  border-color:hsl(var(--warning) / .28)}
.pill.prog{background:hsl(var(--info-bg));color:hsl(var(--info));
  border-color:hsl(var(--info) / .28)}
.pill.done{background:hsl(var(--success-bg));color:hsl(var(--success));
  border-color:hsl(var(--success) / .28)}
.pill.flat{background:hsl(var(--muted));color:hsl(var(--muted-foreground));
  border-color:hsl(var(--border))}

/* --- notices ---------------------------------------------------------- */
/* Padding and a rule down the left edge are what make somebody see one.
   As one line of coloured text it read as ordinary copy. */
.warn,.good{
  display:block;padding:.75rem 1rem;border-radius:calc(var(--radius) - .2rem);
  margin:.7rem 0;font-weight:500;border:1px solid transparent;
  border-left:3px solid currentColor;
}
.warn{background:hsl(var(--danger-bg));color:hsl(var(--danger));
  border-color:hsl(var(--danger) / .3);border-left-color:hsl(var(--danger))}
.good{background:hsl(var(--success-bg));color:hsl(var(--success));
  border-color:hsl(var(--success) / .3);border-left-color:hsl(var(--success))}
.note{background:hsl(var(--warning-bg));border:1px solid hsl(var(--warning) / .3);
  color:hsl(var(--foreground));padding:.8rem 1rem;
  border-radius:calc(var(--radius) - .2rem)}
.warnbox{border:1px solid hsl(var(--warning) / .35);
  background:hsl(var(--warning-bg));border-radius:var(--radius);
  padding:.9rem 1.1rem;margin:1rem 0}
.warnbox h2{margin:.1rem 0 .45rem;font-size:1rem}
.warnbox ul{margin:.3rem 0 .5rem;padding-left:1.2rem}

/* --- buttons and links-as-buttons ------------------------------------- */
.acts{display:flex;gap:.45rem;flex-wrap:wrap;margin-top:.8rem;
  align-items:center}
.btn{
  display:inline-flex;align-items:center;justify-content:center;gap:.4rem;
  height:2.2rem;padding:0 .85rem;border-radius:calc(var(--radius) - .2rem);
  text-decoration:none;font-size:.86rem;font-weight:500;
  border:1px solid hsl(var(--input));
  background:hsl(var(--card));color:hsl(var(--foreground));
  cursor:pointer;white-space:nowrap;
}
.btn:hover{background:hsl(var(--accent));text-decoration:none}
.btn.primary{background:hsl(var(--primary));border-color:hsl(var(--primary));
  color:hsl(var(--primary-foreground));font-weight:600}
.btn.primary:hover{background:hsl(var(--primary) / .9)}
.btn.ghost{border-color:transparent;background:transparent;
  color:hsl(var(--muted-foreground))}
.btn.ghost:hover{background:hsl(var(--accent));color:hsl(var(--foreground))}

button{
  height:2.2rem;padding:0 .95rem;font:inherit;font-size:.86rem;
  font-weight:600;cursor:pointer;
  background:hsl(var(--primary));color:hsl(var(--primary-foreground));
  border:1px solid hsl(var(--primary));
  border-radius:calc(var(--radius) - .2rem);
}
button:hover{background:hsl(var(--primary) / .9)}
button[disabled]{opacity:.5;cursor:not-allowed}
button.ghost{background:transparent;color:hsl(var(--muted-foreground));
  border-color:hsl(var(--input));font-weight:500}
button.ghost:hover{background:hsl(var(--accent));
  color:hsl(var(--foreground))}
button.danger{background:hsl(var(--danger));border-color:hsl(var(--danger));
  color:#fff}

/* --- forms ------------------------------------------------------------ */
label{display:block;margin:.85rem 0 .3rem;font-weight:500;font-size:.86rem}
input[type=text],input[type=email],input[type=password],input[type=date],
input[type=search],input[type=number],textarea,select{
  width:100%;height:2.2rem;padding:0 .6rem;
  border:1px solid hsl(var(--input));
  border-radius:calc(var(--radius) - .2rem);
  font:inherit;font-size:.9rem;
  background:hsl(var(--background));color:hsl(var(--foreground));
}
textarea{min-height:6rem;height:auto;padding:.5rem .6rem;line-height:1.5}
input::placeholder,textarea::placeholder{color:hsl(var(--muted-foreground))}
input:focus-visible,textarea:focus-visible,select:focus-visible{
  outline:2px solid hsl(var(--ring) / .55);outline-offset:0;
  border-color:hsl(var(--ring));
}

/* --- tables ----------------------------------------------------------- */
table{border-collapse:collapse;width:100%;font-size:.88rem;
  background:transparent}
th,td{padding:.55rem .7rem;text-align:left;vertical-align:top;
  border-bottom:1px solid hsl(var(--border))}
th{font-size:.74rem;text-transform:uppercase;letter-spacing:.05em;
  color:hsl(var(--muted-foreground));font-weight:600;
  border-bottom:1px solid hsl(var(--border))}
tbody tr:hover{background:hsl(var(--muted) / .6)}
tbody tr:last-child td{border-bottom:0}
td:has(> form){white-space:nowrap}
.scroll-table{overflow-x:auto;-webkit-overflow-scrolling:touch;
  margin:.5rem 0 1.25rem;border:1px solid hsl(var(--border));
  border-radius:var(--radius);background:hsl(var(--card))}
.scroll-table table{margin:0;width:auto;min-width:100%}
.scroll-table th:first-child,.scroll-table td:first-child{padding-left:1rem}
.scroll-table th:last-child,.scroll-table td:last-child{padding-right:1rem}

.empty{background:hsl(var(--card));border:1px dashed hsl(var(--border));
  border-radius:var(--radius);padding:2.5rem 1rem;text-align:center;
  color:hsl(var(--muted-foreground))}

code{background:hsl(var(--muted));padding:.1rem .35rem;border-radius:4px;
  font-size:.85em;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
pre{white-space:pre-wrap;word-break:break-word;overflow-wrap:break-word;
  background:hsl(var(--muted));color:hsl(var(--foreground));
  padding:.7rem .85rem;border-radius:calc(var(--radius) - .2rem);
  margin:.5rem 0;font-size:.85rem;max-width:100%;
  border:1px solid hsl(var(--border))}

form.inline{display:inline}
/* A form that reveals only the fields the chosen task uses hides its
   wrappers with [hidden]; make that beat any display rule above. */
[hidden]{display:none!important}
.ok{color:hsl(var(--success));font-weight:600}
.err{color:hsl(var(--danger));font-weight:600}

/* --- conversation transcript ------------------------------------------ */
ul.sources{list-style:none;margin:.35rem 0 0;padding:0}
ul.sources li{display:flex;gap:.4rem;align-items:center;flex-wrap:wrap;
  padding:.25rem 0}
.msg{background:hsl(var(--card));border:1px solid hsl(var(--border));
  border-radius:var(--radius);padding:.9rem 1.05rem;margin:.7rem 0}
.msg-hd{display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;
  margin-bottom:.4rem}
.msg .role{font-weight:600;color:hsl(var(--primary-ink));font-size:.86rem}
.msg .time{color:hsl(var(--muted-foreground));font-size:.8rem;
  font-variant-numeric:tabular-nums}

/* --- chips ------------------------------------------------------------ */
.tag{display:inline-block;padding:.12rem .5rem;border-radius:999px;
  font-size:.75rem;font-weight:500;
  background:hsl(var(--muted));color:hsl(var(--foreground));
  border:1px solid transparent;text-decoration:none}
a.tag:hover{text-decoration:none;border-color:hsl(var(--input))}
.tag.down,.tag.flagged{background:hsl(var(--danger-bg));
  color:hsl(var(--danger))}
.tag.up,.tag.done{background:hsl(var(--success-bg));
  color:hsl(var(--success))}
.tag.refuse,.tag.low-conf{background:hsl(var(--warning-bg));
  color:hsl(var(--warning))}
.tag.rated{background:hsl(var(--info-bg));color:hsl(var(--info))}
.tag.all,.tag.dim{background:hsl(var(--muted));
  color:hsl(var(--muted-foreground))}
/* What the classifier decided this question was. Deliberately a different
   shape from the problem chips beside it -- square, monospace, no colour
   of its own -- because "the bot read this as room_booking" is a FACT
   about the turn, not something wrong with it. Reading it as a warning is
   exactly the confusion to avoid. */
.tag.intent{background:hsl(var(--muted));color:hsl(var(--muted-foreground));
  border-radius:4px;border-color:hsl(var(--border));
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:.72rem;letter-spacing:0}
.filter-bar{display:flex;gap:.4rem;flex-wrap:wrap;margin:.7rem 0 1.25rem}
.filter-bar a.tag{padding:.3rem .75rem;border-color:hsl(var(--border))}
.filter-bar a.tag:hover{background:hsl(var(--accent))}
.filter-bar a.tag.active{background:hsl(var(--primary) / .1);
  color:hsl(var(--primary-ink));border-color:hsl(var(--primary) / .45);
  font-weight:600}
.pager{display:flex;align-items:center;gap:.3rem;flex-wrap:wrap;
  font-size:.85rem}

/* --- rendered ETL diff ------------------------------------------------ */
/* The report is markdown we generate, so it is shown as markdown rather
   than as the raw text an editor would see. */
.md{line-height:1.6}
.md h2,.md h3,.md h4{margin:1.5rem 0 .55rem;line-height:1.25}
.md h2{font-size:1.15rem}
.md h3{font-size:1rem}
.md h4{font-size:.92rem;color:hsl(var(--muted-foreground))}
.md p{margin:.55rem 0}
.md ul{margin:.45rem 0 .85rem;padding-left:1.25rem}
.md li{margin:.18rem 0}
.md blockquote{margin:.8rem 0;padding:.6rem 1rem;
  border-left:3px solid hsl(var(--border));
  background:hsl(var(--muted) / .7);
  border-radius:0 calc(var(--radius) - .3rem) calc(var(--radius) - .3rem) 0;
  color:hsl(var(--foreground))}
.md code{background:hsl(var(--muted));padding:.08rem .32rem;border-radius:4px}
.md .scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;
  margin:.6rem 0 1.1rem;border:1px solid hsl(var(--border));
  border-radius:var(--radius)}
.md .scroll table{margin:0;width:auto;min-width:100%}
.joblog{max-height:22rem;overflow:auto}

@media (prefers-reduced-motion:reduce){
  *{transition:none!important;animation:none!important}
}
"""

# --- icons ----------------------------------------------------------------
#
# Inline SVG, not an icon font and not emoji. A font is a network request
# the console does not otherwise need, and emoji render as somebody else's
# artwork at a size we do not control -- on one machine a flat glyph, on
# the next a full-colour cartoon three sizes too big. These are lucide
# paths, stroked in currentColor so they follow the nav item they sit in.
_ICONS = {
    "overview": '<rect width="7" height="9" x="3" y="3" rx="1"/>'
                '<rect width="7" height="5" x="14" y="3" rx="1"/>'
                '<rect width="7" height="9" x="14" y="12" rx="1"/>'
                '<rect width="7" height="5" x="3" y="16" rx="1"/>',
    "chat": '<path d="M14 9a2 2 0 0 1-2 2H6l-4 4V4a2 2 0 0 1 2-2h8a2 2 0 0 '
            '1 2 2z"/><path d="M18 9h2a2 2 0 0 1 2 2v11l-4-4h-6a2 2 0 0 1-2'
            '-2v-1"/>',
    "inbox": '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/>'
             '<path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l'
             '-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    "wrench": '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3'
              '.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l'
              '6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
    "database": '<ellipse cx="12" cy="5" rx="9" ry="3"/>'
                '<path d="M3 5V19A9 3 0 0 0 21 19V5"/>'
                '<path d="M3 12A9 3 0 0 0 21 12"/>',
    "money": '<circle cx="12" cy="12" r="10"/><path d="M16 8h-6a2 2 0 1 0 0 '
             '4h4a2 2 0 1 1 0 4H8"/><path d="M12 18V6"/>',
    "power": '<path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.77.04"/>',
    "log": '<path d="M15 12h-5"/><path d="M15 8h-5"/>'
           '<path d="M19 17V5a2 2 0 0 0-2-2H4"/>'
           '<path d="M8 21h12a2 2 0 0 0 2-2v-1a1 1 0 0 0-1-1H11a1 1 0 0 0-1 '
           '1v1a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v2a1 1 0 0 0 1 1h3"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2"/>'
           '<path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/>'
           '<path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/>'
           '<path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/>'
           '<path d="m19.07 4.93-1.41 1.41"/>',
    "moon": '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    "flag": '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-'
            '4 1z"/><line x1="4" x2="4" y1="22" y2="15"/>',
}


def icon(name: str) -> str:
    d = _ICONS.get(name)
    if not d:
        return "<span class='ico'></span>"
    return (
        "<svg class='ico' viewBox='0 0 24 24' width='16' height='16' "
        "fill='none' stroke='currentColor' stroke-width='2' "
        "stroke-linecap='round' stroke-linejoin='round' aria-hidden='true' "
        f"focusable='false'>{d}</svg>"
    )


# --- what is in the sidebar, for whom --------------------------------------
#
# Grouped, because the flat strip this replaces put eight destinations in
# one row of identical words: "where am I" and "what else is there" were
# both answered by reading all eight. The groups are named for the JOB --
# working a queue, running the bot, watching the money -- which is the
# distinction an operator actually navigates by.
#
# /admin/service is under "Run the bot" and is NOT reference: it is the
# stop button. It shipped with no link anywhere in the UI, so taking the
# bot out of service meant knowing the URL by heart.
#
# Each group carries the role it belongs to. A librarian gets the two
# groups that are their job and never sees the spend ladder or the kill
# switch -- not because they are untrusted, but because a console that
# shows you six controls you must not touch is a console you stop reading.
NAV_GROUPS = (
    (ROLE_LIBRARIAN, "", (
        ("/librarian/", "Overview", None, "overview"),
    )),
    (ROLE_LIBRARIAN, "What people asked", (
        ("/librarian/conversations", "Real questions", None, "chat"),
    )),
    (ROLE_LIBRARIAN, "When it is wrong", (
        ("/librarian/ticket", "Report an answer", None, "flag"),
    )),
    (ROLE_OPERATOR, "", (
        ("/admin/", "Overview", None, "overview"),
    )),
    (ROLE_OPERATOR, "Queues", (
        # Conversations sits first because "what did people ask today" is
        # the question asked most often, and until 2026-08-21 the only way
        # to answer it was Flagged -> the `all` preset -> scroll and read
        # timestamps.
        #
        # Flagged had its own entry here until 2026-08-27. It is the same
        # page now -- Conversations grew the date range, the flag presets,
        # the patron's rating and the classified intent -- so a second link
        # would send two names to one destination and invite the reader to
        # hunt for a difference that no longer exists. /admin/review still
        # redirects, for the bookmarks.
        ("/admin/conversations", "Conversations", None, "chat"),
        ("/admin/tickets/view", "Tickets", "tickets", "inbox"),
        ("/admin/corrections/view", "Corrections", None, "wrench"),
    )),
    (ROLE_OPERATOR, "Run the bot", (
        ("/admin/etl", "Corpus review", None, "database"),
        ("/admin/service", "Service", None, "power"),
        ("/admin/audit", "Audit log", None, "log"),
    )),
    (ROLE_OPERATOR, "Money", (
        ("/admin/cost", "Cost", None, "money"),
    )),
)

# Kept for anything that still asks for the flat list.
NAV = tuple(
    (path, label, count_key)
    for role, _lbl, items in NAV_GROUPS if role == ROLE_OPERATOR
    for path, label, count_key, _ico in items
)

_HOME = {ROLE_OPERATOR: "/admin/", ROLE_LIBRARIAN: "/librarian/"}


def nav(current: str, key: str = "", counts: Optional[dict] = None,
        role: str = ROLE_OPERATOR) -> str:
    """The sidebar. `current` is the path to mark as where you are;
    `counts` puts a badge on the queues that have work waiting."""
    kq = f"?key={e(key)}" if key else ""
    out = []
    for grp_role, label, items in NAV_GROUPS:
        if grp_role != role:
            continue
        rows = []
        for path, text, count_key, ico in items:
            on = " on" if current == path else ""
            badge = ""
            if counts and count_key and counts.get(count_key):
                badge = f"<span class='badge'>{e(counts[count_key])}</span>"
            aria = " aria-current='page'" if on else ""
            rows.append(f"<a class='item{on}' href='{e(path)}{kq}'{aria}>"
                        f"{icon(ico)}<span>{e(text)}</span>{badge}</a>")
        head = f"<div class='lbl'>{e(label)}</div>" if label else ""
        out.append(f"<div class='navgroup'>{head}{''.join(rows)}</div>")
    return "".join(out)


def _brand(key: str, role: str) -> str:
    href = _HOME.get(role, "/admin/") + (f"?key={e(key)}" if key else "")
    which = "Librarian console" if role == ROLE_LIBRARIAN else "Operator console"
    return (f"<a class='brand' href='{href}'>"
            f"<span class='mark' aria-hidden='true'>SC</span>"
            f"<span class='name'>Smart Chatbot"
            f"<span class='role'>{e(which)}</span></span></a>")


def _signature(who) -> str:
    """Who the console thinks you are, at the foot of the sidebar.

    Worth the space: the passphrase on dangerous actions is dropped for a
    signed-in caller and kept for one holding the shared key, so "which am
    I right now" stops being a thing you deduce from whether a password box
    appeared.
    """
    if who is None:
        return ""
    if getattr(who, "authenticated", False):
        return (f"<div class='foot'>Signed in as"
                f"<span class='who'>{e(who.uid)}</span>"
                f"<a href='/admin/sso/logout'>Sign out</a></div>")
    return ("<div class='foot'>Signed in with the"
            "<span class='who'>shared key</span>"
            "Dangerous actions still ask for the passphrase.</div>")


# The theme choice, applied BEFORE anything paints.
#
# In <head> and inline, because the alternative is the page rendering in
# the system theme and then flipping -- a flash on every navigation, on
# every page, for the reader who chose the other one. Wrapped in try:
# localStorage throws outright in some privacy modes, and a console that
# will not render because a colour preference could not be read is a
# worse console than one that ignores the preference.
_THEME_BOOT = (
    "<script>(function(){try{var t=localStorage.getItem('mu-admin-theme');"
    "if(t==='dark'||t==='light')"
    "document.documentElement.setAttribute('data-theme',t);}"
    "catch(e){}})();</script>"
)

# The button is rendered hidden and unhidden by its own script, so a
# browser with JavaScript off never shows a control that cannot work. It
# still follows the system theme there, which is what it did before.
_THEME_TOGGLE = (
    "<button type='button' class='themetoggle' id='theme-toggle' hidden"
    " aria-live='polite'>"
    + icon("sun").replace("class='ico'", "class='ico sun'")
    + icon("moon").replace("class='ico'", "class='ico moon'")
    + "<span class='lbl'></span></button>"
    "<script>(function(){var b=document.getElementById('theme-toggle');"
    "if(!b)return;b.hidden=false;"
    "function cur(){var a=document.documentElement.getAttribute('data-theme');"
    "if(a==='dark'||a==='light')return a;"
    "return window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)')"
    ".matches?'dark':'light';}"
    "function paint(){var c=cur();"
    "b.querySelector('.lbl').textContent=(c==='dark'?'Dark':'Light');"
    # The label says which theme you are IN; the accessible name says what
    # the button DOES -- a screen reader user gets no icon to read.
    "b.setAttribute('aria-label','Switch to '+(c==='dark'?'light':'dark')+' mode');}"
    "b.addEventListener('click',function(){var n=cur()==='dark'?'light':'dark';"
    "document.documentElement.setAttribute('data-theme',n);"
    "try{localStorage.setItem('mu-admin-theme',n);}catch(e){}paint();});"
    "paint();})();</script>"
)


def page(title: str, body: str, *, current: str = "", key: str = "",
         counts: Optional[dict] = None, refresh_s: int = 0,
         role: str = "", who=None, chrome: bool = True,
         refresh_to: str = "") -> str:
    """The shell every admin surface renders into.

    `refresh_s` makes the page reload itself while something is running.
    Without it the corpus page told the reader to "reload for progress",
    which is a job for the page, not the reader: press Fetch, watch
    nothing visibly change, conclude it did not work. It did -- that run
    finished in 46 seconds.

    The refresh names where to go, and that is not decoration. A bare
    `content='5'` reloads whatever URL the document happens to be sitting
    at -- and this shell is returned from POST handlers too, so pressing
    Fetch gave the browser a page at /admin/etl/fetch which it re-requested
    as a GET five seconds later. That route only accepts POST, so the
    reader watched the console replace itself with a bare
    `{"detail":"Method Not Allowed"}` on an unstyled page. Reported
    2026-08-29. Point the refresh at the surface's own GET view instead.

    `who` is the Caller from the guard. It picks which sidebar to draw and
    signs the foot of it; passing nothing draws the operator console,
    which is what every caller got before there were two.

    `chrome=False` drops the sidebar for a page shared outside the group.
    The report form reaches any member of library staff who has the link,
    and every destination in that nav is a door they cannot open -- a menu
    of locked doors is worse than no menu.
    """
    role = role or (getattr(who, "role", "") or ROLE_OPERATOR)
    meta_refresh = ""
    if refresh_s:
        # An explicit destination wins: a page that exists to hand the
        # reader on somewhere else is not reloading itself.
        where = refresh_to or (
            f"{current}?key={e(key)}" if (current and key) else current)
        content = f"{int(refresh_s)}; url={where}" if where else str(int(refresh_s))
        meta_refresh = f"<meta http-equiv='refresh' content='{content}'>"

    # Staff-facing pages are NOT "admin". The report form and the test-mode
    # link reach any member of library staff who has the link, and a browser
    # tab reading "Smart Chatbot admin" tells them they are somewhere they
    # are not -- which is how a link gets forwarded with an apology on it.
    title_tag = (f"<title>{e(title)} — Smart Chatbot admin</title>" if chrome
                 else f"<title>{e(title)} — Miami University Libraries</title>")
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta name='color-scheme' content='light dark'>"
        f"{_THEME_BOOT}"
        f"{meta_refresh}"
        f"{title_tag}"
        f"<style>{STYLE}</style></head>"
        + ("<body>"
           "<div class='shell'>"
           "<aside class='sidebar'>"
           f"{_brand(key, role)}"
           f"{nav(current, key, counts, role)}"
           f"{_THEME_TOGGLE}"
           f"{_signature(who)}"
           "</aside>"
           f"<main>{body}</main>"
           "</div></body></html>"
           if chrome else
           "<body class='plain'>"
           "<header class='topbar'><div class='wrap'>"
           "<span class='mark' aria-hidden='true'>SC</span>"
           "<span class='name'>Smart Chatbot"
           "<span class='role'>Library staff</span></span>"
           f"{_THEME_TOGGLE}"
           "</div></header>"
           f"<main>{body}</main></body></html>")
    )


def stat_card(href: str, n: object, label: str, *, needs: bool = False) -> str:
    """A big-number tile. `needs=True` colors it as work-to-do so the
    dashboard answers "is there anything for me?" without reading."""
    cls = "stat needs" if needs else "stat calm"
    return (f"<a class='{cls}' href='{e(href)}'>"
            f"<div class='n'>{e(n)}</div>"
            f"<div class='lbl'>{e(label)}</div></a>")


_PILL_CLASS = {
    "open": "open",
    "in_progress": "prog",
    "reviewed": "prog",   # legacy value, shown as in-progress
    "done": "done",
}
_PILL_LABEL = {
    "open": "open",
    "in_progress": "in progress",
    "reviewed": "in progress",
    "done": "done",
}


def pill(status: str, *, extra: str = "") -> str:
    """Status pill using ONE vocabulary across every surface."""
    s = (status or "open").lower()
    cls = _PILL_CLASS.get(s, "flat")
    label = _PILL_LABEL.get(s, s)
    return f"<span class='pill {cls}'>{e(label)}</span>{extra}"


def action(href: str, label: str, *, primary: bool = False,
           ghost: bool = False) -> str:
    cls = "btn primary" if primary else ("btn ghost" if ghost else "btn")
    return f"<a class='{cls}' href='{e(href)}'>{e(label)}</a>"


def empty(msg: str) -> str:
    return f"<div class='empty'>{e(msg)}</div>"


__all__ = ["NAV", "NAV_GROUPS", "STYLE", "action", "e", "empty", "icon",
           "nav", "page", "pill", "stat_card"]


def pager(base: str, *, page: int, per: int, total: int,
          key: str = "", extra: str = "") -> str:
    """Page links for a list view. Empty when there is only one page.

    `base` is the path without a query string; `extra` is any other query
    the page needs to keep (a filter, a date). The count is always shown --
    a list that displays 50 of 400 without saying so is a list that hides
    350 of them, which is the complaint this exists to answer.
    """
    pages = max(1, -(-total // max(1, per)))
    if pages <= 1:
        return ""
    kq = f"&key={e(key)}" if key else ""
    first, last = (page - 1) * per + 1, min(page * per, total)

    def lnk(p: int, label: str, off: bool) -> str:
        if off:
            return f"<span class='tag dim'>{label}</span>"
        return (f"<a class='tag' href='{e(base)}?page={p}&per={per}"
                f"{extra}{kq}'>{label}</a>")

    return (
        f"<div class='pager' style='margin:.8rem 0'>"
        f"{lnk(1, '&laquo; first', page == 1)} "
        f"{lnk(page - 1, '&lsaquo; prev', page == 1)} "
        f"<span class='dim' style='margin:0 .5rem'>{first}&ndash;{last} "
        f"of {total}</span> "
        f"{lnk(page + 1, 'next &rsaquo;', page >= pages)} "
        f"{lnk(pages, 'last &raquo;', page >= pages)}</div>"
    )


def page_bounds(page: int, per: int, *, per_max: int = 200) -> tuple:
    """(page, per, offset) clamped to sane values.

    Centralised so a hand-edited `?per=100000` cannot turn one page load
    into a full table scan on a 4GB box.
    """
    page = max(1, int(page or 1))
    per = min(max(int(per or 50), 10), per_max)
    return page, per, (page - 1) * per
