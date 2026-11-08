// applies the saved colour theme before first paint (kept in its own file because the portal bans inline scripts)
try { var t = localStorage.getItem('pps-theme'); if (t) document.documentElement.dataset.theme = t; } catch (e) { /* storage blocked: follow the system */ }
