// ============================================================
// DAILY BASEBALL SUMMARY — Google Apps Script
// ============================================================
// Pulls yesterday's scores, pitching/batting highlights, and
// standings for your configured MLB and MiLB teams.
// Sends a formatted email to your Gmail every morning.
//
// SETUP (5 minutes):
//   1. Go to https://script.google.com
//   2. Click "New Project"
//   3. Delete the placeholder code and paste this entire file
//   4. Click the Save icon (or Ctrl+S), name it "Daily Baseball Summary"
//   5. Click "Run" (play button) with "main" selected in the dropdown
//   6. Google will ask for permissions — click through to allow
//   7. Check your email for the test report
//   8. To schedule: click the clock icon (Triggers) on the left sidebar
//      → Add Trigger → function: main → time-driven → day timer → 8am-9am
//
// That's it. Every morning, Google runs this and emails you.
// ============================================================

// ─────────────────────────────────────────────────────────────
// CONFIGURATION
// ─────────────────────────────────────────────────────────────

const CONFIG = {
  // Your email (where the summary gets sent)
  emailTo: "malfonsin13@gmail.com",

  // Timezone for "yesterday" calculation
  timezone: "America/New_York",

  // Teams to track
  // sportId: 1=MLB, 11=AAA, 12=AA, 13=High-A, 14=Single-A
  teams: [
    // MLB
    { name: "Milwaukee Brewers", sportId: 1 },
    { name: "Detroit Tigers", sportId: 1 },
    { name: "Houston Astros", sportId: 1 },
    // Triple-A
    { name: "Toledo Mud Hens", sportId: 11 },
    // Double-A
    { name: "Erie SeaWolves", sportId: 12 },
    // High-A
    { name: "West Michigan Whitecaps", sportId: 13 },
    { name: "Wisconsin Timber Rattlers", sportId: 13 },
    // Single-A
    { name: "Lakeland Flying Tigers", sportId: 14 },
    { name: "Fayetteville Woodpeckers", sportId: 14 },
    { name: "Wilson Warbirds", sportId: 14 },
  ],
};

const SPORT_LABELS = {
  1: "MLB",
  11: "Triple-A",
  12: "Double-A",
  13: "High-A",
  14: "Single-A",
};

const MLB_LEAGUE_IDS = "103,104";

const MILB_LEAGUE_IDS = {
  11: "112,117",
  12: "113,114",
  13: "118,115",
  14: "110,116,119",
};

const BASE_URL = "https://statsapi.mlb.com/api/v1";

// ─────────────────────────────────────────────────────────────
// API HELPERS
// ─────────────────────────────────────────────────────────────

function apiGet(endpoint, params) {
  let url = `${BASE_URL}/${endpoint}`;
  if (params) {
    const qs = Object.entries(params)
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
      .join("&");
    url += `?${qs}`;
  }
  try {
    const resp = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
    if (resp.getResponseCode() !== 200) {
      Logger.log(`API error ${resp.getResponseCode()}: ${url}`);
      return null;
    }
    return JSON.parse(resp.getContentText());
  } catch (e) {
    Logger.log(`API exception: ${e.message} — ${url}`);
    return null;
  }
}

// ─────────────────────────────────────────────────────────────
// TEAM ID RESOLUTION
// ─────────────────────────────────────────────────────────────

function resolveTeamId(teamName, sportId, season) {
  const data = apiGet("teams", { sportId: sportId, season: season });
  if (!data || !data.teams) return null;

  const nameLower = teamName.toLowerCase();

  // Exact match
  for (const t of data.teams) {
    if (t.name.toLowerCase() === nameLower) return t.id;
  }

  // Fuzzy match
  for (const t of data.teams) {
    const apiName = t.name.toLowerCase();
    const shortName = (t.shortName || "").toLowerCase();
    const clubName = (t.clubName || "").toLowerCase();
    if (
      nameLower.includes(clubName) || clubName.includes(nameLower) ||
      nameLower.includes(apiName) || apiName.includes(nameLower) ||
      nameLower.includes(shortName) || shortName.includes(nameLower)
    ) {
      return t.id;
    }
  }

  return null;
}

function resolveAllTeamIds(season) {
  // Use script properties as cache
  const props = PropertiesService.getScriptProperties();
  const teams = [];

  for (const team of CONFIG.teams) {
    const cacheKey = `teamId_${team.name}_${team.sportId}`;
    let teamId = props.getProperty(cacheKey);

    if (!teamId) {
      Logger.log(`Resolving ID for ${team.name} (sportId=${team.sportId})...`);
      teamId = resolveTeamId(team.name, team.sportId, season);
      if (teamId) {
        props.setProperty(cacheKey, String(teamId));
      } else {
        Logger.log(`⚠️ Could not find: ${team.name} (sportId=${team.sportId})`);
        continue;
      }
    }

    teams.push({
      name: team.name,
      sportId: team.sportId,
      teamId: parseInt(teamId),
      level: SPORT_LABELS[team.sportId] || "Unknown",
    });
  }

  return teams;
}

// ─────────────────────────────────────────────────────────────
// GAME DATA
// ─────────────────────────────────────────────────────────────

function getSchedule(teamId, sportId, dateStr) {
  return apiGet("schedule", {
    sportId: sportId,
    date: dateStr,
    teamId: teamId,
    hydrate: "linescore,decisions,probablePitcher,person",
  });
}

function getBoxscore(gamePk) {
  return apiGet(`game/${gamePk}/boxscore`);
}

// ─────────────────────────────────────────────────────────────
// FORMATTING
// ─────────────────────────────────────────────────────────────

function formatPitcherLine(stats, name) {
  const s = stats.pitching || {};
  const ip = s.inningsPitched || "0";
  const h = s.hits || 0;
  const r = s.runs || 0;
  const er = s.earnedRuns || 0;
  const k = s.strikeOuts || 0;
  const bb = s.baseOnBalls || 0;
  const hr = s.homeRuns || 0;
  const pc = s.pitchesThrown || s.numberOfPitches || "?";
  const era = s.era || "?";

  let line = `${name}: ${ip} IP, ${h} H, ${r} R (${er} ER), ${k} K, ${bb} BB`;
  if (hr > 0) line += `, ${hr} HR`;
  line += `, ${pc} pitches, ${era} ERA`;
  return line;
}

function extractGameSummary(game, teamId, boxscore) {
  const lines = [];
  const status = (game.status || {}).detailedState || "Unknown";

  if (status === "Postponed" || status === "Suspended" || status === "Cancelled") {
    return [`  Game ${status.toLowerCase()}.`];
  }
  if (!["Final", "Completed Early", "Game Over"].includes(status)) {
    return [`  Game status: ${status}`];
  }

  // Score
  const homeTeam = game.teams.home;
  const awayTeam = game.teams.away;
  const homeName = homeTeam.team.name;
  const awayName = awayTeam.team.name;
  const homeScore = homeTeam.score || 0;
  const awayScore = awayTeam.score || 0;
  const homeId = homeTeam.team.id;

  const isHome = teamId === homeId;
  const ourScore = isHome ? homeScore : awayScore;
  const theirScore = isHome ? awayScore : homeScore;
  const result = ourScore > theirScore ? "W" : ourScore < theirScore ? "L" : "T";
  const location = isHome ? "vs" : "@";
  const opponent = isHome ? awayName : homeName;

  // Extras?
  const linescore = game.linescore || {};
  const innings = linescore.currentInning || 9;
  const extras = innings > 9 ? ` (${innings})` : "";

  lines.push(`  ${result} ${ourScore}-${theirScore}${extras} ${location} ${opponent}`);

  // Decisions
  const decisions = game.decisions || {};
  const decisionParts = [];
  if (decisions.winner) decisionParts.push(`W: ${decisions.winner.fullName || "?"}`);
  if (decisions.loser) decisionParts.push(`L: ${decisions.loser.fullName || "?"}`);
  if (decisions.save) decisionParts.push(`SV: ${decisions.save.fullName || "?"}`);
  if (decisionParts.length > 0) {
    lines.push(`  ${decisionParts.join(" | ")}`);
  }

  // Pitching + Batting from boxscore
  if (boxscore) {
    for (const side of ["home", "away"]) {
      const teamBox = (boxscore.teams || {})[side] || {};
      const boxTeamId = (teamBox.team || {}).id;
      if (boxTeamId !== teamId) continue;

      const pitchers = teamBox.pitchers || [];
      const batters = teamBox.batters || [];
      const players = teamBox.players || {};

      // Starter (first pitcher)
      if (pitchers.length > 0) {
        const pid = pitchers[0];
        const p = players[`ID${pid}`] || {};
        const name = (p.person || {}).fullName || "Unknown";
        const stats = p.stats || {};
        if (stats.pitching) {
          lines.push(`  SP: ${formatPitcherLine(stats, name)}`);
        }
      }

      // Notable batters
      const notable = [];
      for (const bid of batters) {
        const p = players[`ID${bid}`] || {};
        const name = (p.person || {}).fullName || "Unknown";
        const s = (p.stats || {}).batting || {};
        if (!s.atBats && s.atBats !== 0) continue;

        const h = s.hits || 0;
        const ab = s.atBats || 0;
        const hr = s.homeRuns || 0;
        const rbi = s.rbi || 0;
        const doubles = s.doubles || 0;
        const triples = s.triples || 0;
        const bb = s.baseOnBalls || 0;
        const sb = s.stolenBases || 0;

        const isNotable =
          hr > 0 || rbi >= 3 || h >= 3 ||
          (h >= 2 && (doubles > 0 || triples > 0 || rbi >= 2));
        if (!isNotable) continue;

        const parts = [`${h}-${ab}`];
        if (hr > 0) parts.push(`${hr} HR`);
        if (doubles > 0) parts.push(`${doubles} 2B`);
        if (triples > 0) parts.push(`${triples} 3B`);
        if (rbi > 0) parts.push(`${rbi} RBI`);
        if (bb > 0) parts.push(`${bb} BB`);
        if (sb > 0) parts.push(`${sb} SB`);

        notable.push(`${name} (${parts.join(", ")})`);
      }

      if (notable.length > 0) {
        lines.push(`  Standouts: ${notable.join(" | ")}`);
      }
    }
  }

  return lines;
}

// ─────────────────────────────────────────────────────────────
// STANDINGS
// ─────────────────────────────────────────────────────────────

function getStandingsForTeam(teamId, sportId, season) {
  let leagueIds;
  if (sportId === 1) {
    leagueIds = MLB_LEAGUE_IDS;
  } else {
    leagueIds = MILB_LEAGUE_IDS[sportId] || "";
  }
  if (!leagueIds) return null;

  const data = apiGet("standings", {
    leagueId: leagueIds,
    season: season,
    hydrate: "team",
  });
  if (!data || !data.records) return null;

  for (const record of data.records) {
    const divName = (record.division || {}).name || "";
    const leagueName = (record.league || {}).name || "";
    for (const tr of record.teamRecords || []) {
      if (tr.team.id === teamId) {
        const w = tr.wins || 0;
        const l = tr.losses || 0;
        const gb = tr.gamesBack || "-";
        const divRank = tr.divisionRank || "?";
        const pct = tr.winningPercentage || "?";

        const streakObj = tr.streak || {};
        let streak = "";
        if (streakObj.streakType && streakObj.streakNumber) {
          streak = `, ${streakObj.streakType[0]}${streakObj.streakNumber}`;
        }

        const division = divName || leagueName || "?";
        const gbStr = gb !== "-" && gb !== "0" ? `, ${gb} GB` : "";

        return `${w}-${l} (.${pct}), ${divRank} in ${division}${gbStr}${streak}`;
      }
    }
  }
  return null;
}

// ─────────────────────────────────────────────────────────────
// BUILD REPORT
// ─────────────────────────────────────────────────────────────

function buildReport(targetDate) {
  const dateStr = Utilities.formatDate(targetDate, CONFIG.timezone, "yyyy-MM-dd");
  const displayDate = Utilities.formatDate(targetDate, CONFIG.timezone, "EEEE, MMMM dd, yyyy");
  const season = parseInt(Utilities.formatDate(targetDate, CONFIG.timezone, "yyyy"));

  const output = [];
  output.push("=".repeat(60));
  output.push(`⚾ DAILY BASEBALL SUMMARY — ${displayDate}`);
  output.push("=".repeat(60));

  // Resolve team IDs
  const teams = resolveAllTeamIds(season);
  if (teams.length === 0) {
    output.push("No teams resolved. Check CONFIG.teams.");
    return output.join("\n");
  }

  // Group by level
  const levelOrder = ["MLB", "Triple-A", "Double-A", "High-A", "Single-A"];
  for (const level of levelOrder) {
    const levelTeams = teams.filter((t) => t.level === level);
    if (levelTeams.length === 0) continue;

    output.push("");
    output.push(`${"─".repeat(5)} ${level} ${"─".repeat(52 - level.length)}`);

    for (const team of levelTeams) {
      output.push("");

      // Standings
      const standings = getStandingsForTeam(team.teamId, team.sportId, season);
      const standingsStr = standings ? ` | ${standings}` : "";
      output.push(`📋 ${team.name}${standingsStr}`);

      // Schedule
      const schedule = getSchedule(team.teamId, team.sportId, dateStr);
      const games = [];
      if (schedule && schedule.dates) {
        for (const d of schedule.dates) {
          games.push(...(d.games || []));
        }
      }

      if (games.length === 0) {
        output.push("  No game scheduled.");
        continue;
      }

      for (const game of games) {
        const gamePk = game.gamePk;
        const status = (game.status || {}).detailedState || "Unknown";

        let boxscore = null;
        if (["Final", "Completed Early", "Game Over"].includes(status) && gamePk) {
          boxscore = getBoxscore(gamePk);
        }

        const summary = extractGameSummary(game, team.teamId, boxscore);
        output.push(...summary);
      }
    }
  }

  output.push("");
  output.push("=".repeat(60));
  const now = new Date();
  const genTime = Utilities.formatDate(now, CONFIG.timezone, "hh:mm a 'ET,' MMMM dd, yyyy");
  output.push(`Generated: ${genTime}`);
  output.push("=".repeat(60));

  return output.join("\n");
}

// ─────────────────────────────────────────────────────────────
// MAIN — This is what runs on schedule
// ─────────────────────────────────────────────────────────────

function main() {
  // Calculate yesterday in ET
  const now = new Date();
  const formatter = Utilities.formatDate(now, CONFIG.timezone, "yyyy-MM-dd");
  const todayET = new Date(formatter + "T00:00:00");
  const yesterday = new Date(todayET.getTime() - 24 * 60 * 60 * 1000);

  const report = buildReport(yesterday);
  const dateDisplay = Utilities.formatDate(yesterday, CONFIG.timezone, "MMM dd");

  // Send email
  GmailApp.sendEmail(CONFIG.emailTo, `⚾ Baseball Summary — ${dateDisplay}`, report, {
    name: "Baseball Bot",
    htmlBody: `<pre style="font-family: Consolas, Monaco, 'Courier New', monospace; font-size: 13px; line-height: 1.5; background: #1a1a2e; color: #e0e0e0; padding: 20px; border-radius: 8px;">${report}</pre>`,
  });

  Logger.log(`Report sent for ${dateDisplay}`);
}

// Run for a specific date (for testing)
function testSpecificDate() {
  const targetDate = new Date("2026-04-05");
  const report = buildReport(targetDate);
  Logger.log(report);

  GmailApp.sendEmail(CONFIG.emailTo, "⚾ Baseball Summary — TEST", report, {
    name: "Baseball Bot",
    htmlBody: `<pre style="font-family: Consolas, Monaco, 'Courier New', monospace; font-size: 13px; line-height: 1.5; background: #1a1a2e; color: #e0e0e0; padding: 20px; border-radius: 8px;">${report}</pre>`,
  });
}

// Clear cached team IDs (run if a team moves/renames)
function clearCache() {
  PropertiesService.getScriptProperties().deleteAllProperties();
  Logger.log("Cache cleared. Team IDs will re-resolve on next run.");
}
