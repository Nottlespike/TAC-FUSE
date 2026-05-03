const WORLD_M = 1200;
const MAX_VISIBLE_DETECTION_LABELS = 2;
const AOI_TILE = {
  label: "1.2 km local AOI",
  cropX: 0.31,
  cropY: 0.43,
  cropScale: 0.18,
  meshStepM: 120,
};
const BASE = { x: 120, y: 850 };
const FIELD_VIEW_ANCHOR = { x: 610, y: 590, z: 120 };
const FIELD_VIEW_DEFAULT = {
  yaw: 0,
  pitch: 0.86,
  zoom: 1.0,
};
const colors = {
  alpha: "#55d6a6",
  bravo: "#79b8ff",
  charlie: "#ff5d5d",
  delta: "#e6c35c",
  team: "#d8e0dc",
  object: "#d9a05f",
  signal: "#d7d95f",
  personnel: "#b8d8ff",
  micro: "#c9a3ff",
  unknown: "#ff9f6e",
};

const earthImagery = {
  src: "../assets/visual/earth/blue_marble_january_5400.jpg",
  image: new Image(),
  ready: false,
  failed: false,
};
const edgeCompute = window.TAC_FUSE_EDGE_COMPUTE || null;
const classifierCue = window.TAC_FUSE_CLASSIFIER_CUE || null;
const liveClassifierCue = classifierCue?.ready ? classifierCue.classification : null;

const CLASSIFIER_CUE_LABELS = {
  clear_corridor: "Clear Corridor",
  dense_multi_asset_formation: "Dense Formation",
  drone_near_restricted_area: "Drone Near Restricted",
  low_altitude_clutter: "Low Altitude Clutter",
  low_power_return_corridor: "Low Power Return",
  reduced_visibility_field_conditions: "Reduced Visibility",
};

const hazards = [
  { id: "rf-denial-east", label: "RF Denial", x: 610, y: 360, r: 105, severity: "critical" },
  { id: "return-corridor", label: "Return Corridor", x: 330, y: 790, r: 95, severity: "watch" },
  { id: "terrain-mask", label: "Terrain Mask", x: 760, y: 650, r: 82, severity: "watch" },
];
const ROUTE_GUARD_HALF_WIDTH_M = 44;
const ROUTE_GUARD_PATH = [
  { x: 65, y: 990 },
  { x: 255, y: 845 },
  { x: 455, y: 705 },
  { x: 695, y: 650 },
  { x: 950, y: 535 },
  { x: 1138, y: 450 },
];
// Contributor feeds to the fusion node - each has freshness/confidence/latency
const feeds = [
  {
    id: "uav-alpha",
    key: "alpha",
    callsign: "Alpha",
    type: "quadrotor",
    x: 260,
    y: 760,
    z: 122,
    heading: -35,
    speed: 32,
    battery: 96,
    command: "patrol",
    cruiseSpeed: 32,
    cruiseAltitude: 122,
    target: { x: 690, y: 330 },
    orbitPhase: 0.1,
    freshness: 0.96,
    confidence: 0.88,
    latency: 42,
    npu: { device: "NPU", cue: "Route Contact", confidence: 0.86 },
  },
  {
    id: "uav-bravo",
    key: "bravo",
    callsign: "Bravo",
    type: "fixed-wing",
    x: 170,
    y: 430,
    z: 142,
    heading: 20,
    speed: 44,
    battery: 91,
    command: "relay",
    cruiseSpeed: 44,
    cruiseAltitude: 142,
    target: { x: 780, y: 500 },
    orbitPhase: 1.4,
    freshness: 0.88,
    confidence: 0.72,
    latency: 78,
    npu: { device: "NPU", cue: "Air Track", confidence: 0.79 },
  },
  {
    id: "uav-charlie",
    key: "charlie",
    callsign: "Charlie",
    type: "quadrotor",
    x: 705,
    y: 265,
    z: 98,
    heading: 160,
    speed: 27,
    battery: 88,
    command: "scout",
    cruiseSpeed: 27,
    cruiseAltitude: 98,
    target: { x: 505, y: 470 },
    orbitPhase: 2.2,
    freshness: 0.93,
    confidence: 0.91,
    latency: 31,
    npu: { device: "NPU", cue: "RF Source", confidence: 0.88 },
  },
  {
    id: "uav-delta",
    key: "delta",
    callsign: "Delta",
    type: "quadrotor",
    x: 800,
    y: 640,
    z: 164,
    heading: -110,
    speed: 30,
    battery: 86,
    command: "overwatch",
    cruiseSpeed: 30,
    cruiseAltitude: 164,
    target: { x: 640, y: 610 },
    orbitPhase: 3.1,
    freshness: 0.81,
    confidence: 0.65,
    latency: 120,
    npu: { device: "NPU", cue: "Unknown Cue", confidence: 0.74 },
  },
];

const groundTeam = {
  id: "ground-team-1",
  key: "team",
  callsign: "Team 1",
  type: "ground",
  x: 540,
  y: 820,
  z: 2,
  heading: 0,
  speed: 2,
  battery: 100,
  command: "hold",
  freshness: 1.0,
  confidence: 0.95,
  latency: 8,
};

const sceneClassTargets = [
  {
    id: "scene-vehicle-17",
    key: "object",
    callsign: "Track 17",
    type: "vehicle",
    x: 676,
    y: 486,
    z: 7,
    heading: 18,
    speed: 7,
    routeIndex: 4,
    trainingClass: liveClassifierCue?.class_label || "four_wheeled_vehicle",
    classifierCue: liveClassifierCue
      ? {
          label: liveClassifierCue.class_label,
          confidence: liveClassifierCue.confidence,
          latencyMs: liveClassifierCue.inference_latency_ms,
          modelId: liveClassifierCue.model_id,
        }
      : null,
    freshness: 0.9,
    confidence: liveClassifierCue?.confidence || 0.78,
    latency: liveClassifierCue?.inference_latency_ms
      ? Math.round(liveClassifierCue.inference_latency_ms)
      : 58,
  },
  {
    id: "scene-signal-04",
    key: "signal",
    callsign: "Signal 04",
    type: "rf-source",
    x: 586,
    y: 356,
    z: 5,
    heading: 0,
    speed: 1.1,
    driftPhase: 0.4,
    freshness: 0.84,
    confidence: 0.7,
    latency: 66,
  },
  {
    id: "scene-personnel-12",
    key: "personnel",
    callsign: "Group 12",
    type: "personnel",
    x: 744,
    y: 620,
    z: 3,
    heading: 0,
    speed: 1.4,
    patrolIndex: 1,
    patrolPath: [
      { x: 744, y: 620 },
      { x: 690, y: 665 },
      { x: 625, y: 636 },
    ],
    freshness: 0.87,
    confidence: 0.73,
    latency: 63,
  },
  {
    id: "scene-micro-22",
    key: "micro",
    callsign: "Track 22",
    type: "small-uas",
    x: 30,
    y: 470,
    z: 72,
    heading: 82,
    speed: 17,
    routeIndex: 1,
    pathDirection: 1,
    ingressPath: [
      { x: 30, y: 470 },
      { x: 265, y: 520 },
      { x: 540, y: 560 },
      { x: 835, y: 500 },
      { x: 1170, y: 430 },
    ],
    freshness: 0.76,
    confidence: 0.64,
    latency: 71,
  },
  {
    id: "scene-unknown-31",
    key: "unknown",
    callsign: "Unknown 31",
    type: "unknown-contact",
    x: 930,
    y: 520,
    z: 6,
    heading: -28,
    speed: 4.8,
    routeIndex: 4,
    freshness: 0.79,
    confidence: 0.58,
    latency: 74,
    identification: "needs-id",
  },
  {
    id: "scene-unknown-air-09",
    key: "unknown",
    callsign: "Unknown 09",
    type: "unknown-uas",
    x: 860,
    y: 1170,
    z: 90,
    heading: 112,
    speed: 14,
    routeIndex: 1,
    pathDirection: 1,
    ingressPath: [
      { x: 860, y: 1170 },
      { x: 780, y: 930 },
      { x: 610, y: 700 },
      { x: 420, y: 500 },
      { x: 30, y: 360 },
    ],
    freshness: 0.73,
    confidence: 0.53,
    latency: 82,
    identification: "needs-id",
  },
];

let selectedId = "uav-alpha";
let selectedContactId = null;
let connectivityMode = "offline";
let rayPath = edgeCompute?.ray?.accelerated ? "cuda" : "validation";
let simPaused = false;
let simTime = 0;
let lastTick = performance.now();
let commandSeq = 1;
const stagedCommands = [];  // commands staged for sync
const missionLog = [];
let spoolDepth = 0;         // offline spool buffer depth
let syncWatermark = 0;      // timestamp of last staged sync
let syncStaged = false;     // whether a packet is staged for gate
const MAX_MISSION_LOG = 40;  // extended log for replay timeline
const fusedTracks = new Map();
const TRACK_MEMORY_SECONDS = 18;
const TRACK_PRUNE_SECONDS = 45;
const TRACK_ASSOCIATION_RADIUS_M = 55;
const DEMO_INCIDENT_TRIGGER_S = 32;
let nextTrackSerial = 1;
let povHitTargets = [];
const fieldView = {
  ...FIELD_VIEW_DEFAULT,
  dragging: false,
  moved: false,
  startX: 0,
  startY: 0,
  lastX: 0,
  lastY: 0,
};

const localC2Incident = {
  triggered: false,
  active: false,
  label: "Route Contact Incident",
  detail: "RF pressure and unknown route contact detected",
  triggeredAt: null,
  takeoverCommands: 0,
};

// Swarm-wide tasking state — single-operator C2 proof
// Tracks operator commands across all drones for the denied-ops proof path
const swarmTasking = {
  lastCommand: {},   // assetId -> { command, ts }
  history: [],       // array of { assetId, callsign, command, ts }
  retaskCount: 0,
};

// Power posture state — mirrors tac_fuse.power_posture
let powerSource = "battery";        // battery | backpack_generator | ac_mains
let laptopBattery = 100.0;          // fusion node battery 0-100
let cpuLoad = 35.0;                 // estimated CPU load 0-100
const BATTERY_DRAIN_RATE = 100 / 180; // ~0.56%/min
let currentPosture = null;          // Current power posture snapshot

// Workload registry matching power_posture.py WORKLOAD_REGISTRY
const WORKLOAD_CLASSES = {
  local_c2: "safe_offline",
  sensor_fusion: "safe_offline",
  alerting: "safe_offline",
  fusion_spool: "safe_offline",
  collision_bvh: "safe_offline",
  drone_tasking: "safe_offline",
  foundry_export: "safe_offline",
  sensor_emulation: "safe_degraded",
  terrain_mesh: "safe_degraded",
  earth_aoi_cache: "safe_degraded",
  enterprise_sync: "requires_online",
};

function computePosture() {
  // Compute tier
  let tier;
  const hotThreshold = 85;
  const reducedBattery = 40;
  const minimalBattery = 15;

  if (powerSource === "ac_mains") {
    tier = cpuLoad >= hotThreshold ? "reduced" : "full";
  } else if (powerSource === "backpack_generator") {
    tier = cpuLoad >= hotThreshold ? "reduced"
      : laptopBattery < minimalBattery ? "minimal" : "full";
  } else {
    tier = laptopBattery < minimalBattery ? "minimal"
      : laptopBattery < reducedBattery ? "reduced"
      : cpuLoad >= hotThreshold ? "reduced" : "full";
  }

  // Thermal headroom
  const thermal = cpuLoad >= hotThreshold ? "hot" : cpuLoad >= 60 ? "warm" : "nominal";

  // Runtime estimate
  let runtimeMin;
  if (powerSource === "ac_mains") runtimeMin = Infinity;
  else if (powerSource === "backpack_generator") runtimeMin = 360;
  else runtimeMin = laptopBattery > 0 ? laptopBattery / BATTERY_DRAIN_RATE : 0;

  // Classify workloads
  const safe = [];
  const restricted = [];
  for (const [name, cls] of Object.entries(WORKLOAD_CLASSES)) {
    let isSafe = false;
    if (cls === "safe_offline") {
      isSafe = tier !== "minimal" || ["local_c2", "fusion_spool", "alerting"].includes(name);
    } else if (cls === "safe_degraded") {
      isSafe = tier === "full";
    } else if (cls === "requires_online") {
      isSafe = connectivityMode === "online" && tier !== "minimal";
    }
    if (isSafe) safe.push(name);
    else restricted.push(name);
  }

  // Notes
  const notes = [];
  if (powerSource === "battery") {
    if (runtimeMin < 30) notes.push({ text: `Battery Critical: ~${Math.round(runtimeMin)} Min — Switch To Backpack Or AC`, level: "critical" });
    else if (runtimeMin < 60) notes.push({ text: `Battery Low: ~${Math.round(runtimeMin)} Min Remaining`, level: "warn" });
    else notes.push({ text: `Battery: ~${Math.round(runtimeMin)} Min Estimated Runtime`, level: "" });
  } else if (powerSource === "backpack_generator") {
    notes.push({ text: "Backpack Generator Active — Extended Runtime", level: "" });
  } else {
    notes.push({ text: "AC Mains — No Runtime Constraint", level: "" });
  }
  if (tier === "minimal") notes.push({ text: "Minimal: Only C2, Spool, Alerting Active", level: "critical" });
  else if (tier === "reduced") notes.push({ text: "Reduced: Heavy Batch Workloads Paused", level: "warn" });
  if (thermal === "hot") notes.push({ text: "Thermal Throttle: CPU Load Elevated", level: "warn" });
  if (connectivityMode === "offline") notes.push({ text: "Offline: Enterprise Sync Blocked, Local C2 Is Authority", level: "" });
  else if (connectivityMode === "degraded") notes.push({ text: "Degraded: Sync Queued, Awaiting Connectivity", level: "" });

  return { tier, thermal, runtimeMin, safe, restricted, notes };
}

const CONNECTIVITY_LABELS = {
  offline: "Fusion Node Authority",
  degraded: "Local C2 Active",
  online: "Enterprise Sync Enabled",
};
const CONNECTIVITY_CLASSES = {
  offline: "offline",
  degraded: "degraded",
  online: "online",
};

const swarmCanvas = document.querySelector("#swarm-map");
const swarmCtx = swarmCanvas.getContext("2d");
const povCanvas = document.querySelector("#pov-canvas");
const povCtx = povCanvas.getContext("2d");
const overlay = document.querySelector("#pov-overlay");

function setText(selector, text) {
  const element = document.querySelector(selector);
  if (element) element.textContent = text;
}

function latencyClass(latencyMs) {
  return latencyMs < 50 ? "good" : latencyMs < 100 ? "watch" : "critical";
}

function formatLatencyMs(latencyMs) {
  const ms = Math.max(0, latencyMs);
  if (ms >= 1000) {
    const seconds = ms / 1000;
    return `${seconds >= 10 ? Math.round(seconds) : seconds.toFixed(1)} s`;
  }
  if (ms < 10) return `${ms.toFixed(1)} ms`;
  return `${Math.round(ms).toLocaleString()} ms`;
}

function formatMeters(meters) {
  return `${Math.round(meters).toLocaleString()} m`;
}

function routeLengthMeters() {
  let total = 0;
  for (let index = 1; index < ROUTE_GUARD_PATH.length; index += 1) {
    const prev = ROUTE_GUARD_PATH[index - 1];
    const next = ROUTE_GUARD_PATH[index];
    total += Math.hypot(next.x - prev.x, next.y - prev.y);
  }
  return total;
}

function displayCommand(command) {
  const labels = {
    abort: "Abort",
    hold: "Hold",
    overwatch: "Overwatch",
    patrol: "Patrol",
    relay: "Relay",
    resume: "Resume",
    return: "Return",
    scout: "Scout",
  };
  return labels[command] || command;
}

function displayTier(tier) {
  const labels = {
    full: "Full",
    minimal: "Minimal",
    reduced: "Reduced",
  };
  return labels[tier] || tier;
}

function displayClassifierCueLabel(label) {
  if (!label) return "No Model Cue";
  if (CLASSIFIER_CUE_LABELS[label]) return CLASSIFIER_CUE_LABELS[label];
  const cleaned = String(label).replace(/[_-]+/g, " ").trim();
  if (!cleaned) return "No Model Cue";
  return cleaned.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function classifierCueClassification() {
  return classifierCue?.ready && classifierCue.classification ? classifierCue.classification : null;
}

function classifierCueConfidencePct(cue = classifierCueClassification()) {
  const confidence = Number(cue?.confidence || 0);
  return Math.round(clamp(confidence, 0, 1) * 100);
}

function classifierCueDetail() {
  const cue = classifierCueClassification();
  if (!cue) {
    return classifierCue?.error || edgeCompute?.classifier_package?.reason || "No Generated Model Cue";
  }
  const label = displayClassifierCueLabel(cue.class_label);
  const latency = formatLatencyMs(Number(cue.inference_latency_ms || 0));
  return `${label} · ${classifierCueConfidencePct(cue)}% · ${latency}`;
}

function classifierCueRows() {
  const cue = classifierCueClassification();
  if (!cue) return null;
  const candidates = classifierCue?.top_candidates?.length
    ? classifierCue.top_candidates
    : cue.all_candidates || [];
  return candidates.slice(0, 3).map((candidate) => [
    `H100 ${displayClassifierCueLabel(candidate.label)}`,
    clamp(Number(candidate.confidence || 0), 0, 1),
  ]);
}

function geometryBackendLabel() {
  return edgeCompute?.ui?.backend_label || (rayPath === "cuda" ? "Accelerated Geometry" : "Validation Geometry");
}

function edgeComputeSummaryLabel() {
  return edgeCompute?.ui?.summary_label || "Validation RT Control";
}

function edgeNpuLabel() {
  return edgeCompute?.ui?.npu_label || "Edge NPU Unverified";
}

function edgeClassifierLabel() {
  return edgeCompute?.ui?.classifier_label || "H100 Classifier Unverified";
}

function edgeComputeFreshnessLabel() {
  const generatedAt = edgeCompute?.generated_at;
  if (!generatedAt) return "Fallback";
  const timestamp = Date.parse(generatedAt);
  if (Number.isNaN(timestamp)) return "Fallback";
  const staleAfterSeconds = edgeCompute?.ui?.stale_after_seconds || 300;
  const ageSeconds = Math.max(0, (Date.now() - timestamp) / 1000);
  return ageSeconds > staleAfterSeconds ? "Stale" : "Live";
}

function rtControlBackendLabel() {
  return rayPath === "cuda" ? "Accelerated RT" : "Validation RT";
}

earthImagery.image.onload = () => {
  earthImagery.ready = true;
};
earthImagery.image.onerror = () => {
  earthImagery.failed = true;
};
earthImagery.image.src = earthImagery.src;

function allFeeds() {
  return [...feeds, groundTeam];
}

function knownFriendlyFor(asset) {
  const id = asset?.targetId || asset?.id;
  return allFeeds().find((item) => item.id === id) || null;
}

function isKnownFriendly(asset) {
  return Boolean(knownFriendlyFor(asset));
}

function detectableObjects() {
  return [...allFeeds(), ...sceneClassTargets];
}

function selectedFeed() {
  return feeds.find((f) => f.id === selectedId) || feeds[0];
}

function selectedContact() {
  if (!selectedContactId) return null;
  return [...fusedTracks.values()].find((track) => track.id === selectedContactId) || null;
}

function pushLog(text) {
  missionLog.unshift(`T+${simTime.toFixed(1)}s ${text}`);
  missionLog.splice(MAX_MISSION_LOG);
}

function issueCommand(command, targetFeed) {
  const feed = targetFeed || selectedFeed();
  const record = {
    id: `cmd-${String(commandSeq).padStart(3, "0")}`,
    assetId: feed.id,
    callsign: feed.callsign,
    command,
    mode: "fusion-local",
    status: "staged",
    ts: simTime,
  };
  commandSeq += 1;
  stagedCommands.unshift(record);
  stagedCommands.splice(12);

  // Swarm tasking: track last command per drone and detect retasking
  const prevCommand = swarmTasking.lastCommand[feed.id];
  if (prevCommand && prevCommand.command !== command) {
    swarmTasking.retaskCount += 1;
  }
  swarmTasking.lastCommand[feed.id] = { command, ts: simTime };
  swarmTasking.history.unshift({ assetId: feed.id, callsign: feed.callsign, command, ts: simTime });
  swarmTasking.history.splice(20); // keep last 20 entries

  spoolDepth = stagedCommands.length;
  syncStaged = spoolDepth > 0;
  if (syncStaged) {
    syncWatermark = simTime;
  }

  if (command === "return") {
    feed.command = "return";
    feed.target = { ...BASE };
    feed.station = null;
  } else if (command === "hold") {
    feed.command = "hold";
  } else if (command === "patrol") {
    feed.command = "patrol";
    feed.station = { x: 680, y: 360 };
    feed.target = { ...feed.station };
  } else if (command === "abort") {
    feeds.forEach((item) => {
      item.command = "hold";
    });
  } else if (command === "resume") {
    feed.command = "patrol";
  }
  pushLog(`${record.callsign} ${displayCommand(command)} Staged For Sync.`);
}

function issueCommandToDrone(feedId, command) {
  const feed = feeds.find((f) => f.id === feedId);
  if (!feed) return;
  issueCommand(command, feed);
}

function triggerLocalC2Incident() {
  if (localC2Incident.triggered) return;
  localC2Incident.triggered = true;
  localC2Incident.active = true;
  localC2Incident.triggeredAt = simTime;
  connectivityMode = "offline";

  const routeContact = sceneClassTargets.find((target) => target.id === "scene-unknown-31");
  if (routeContact) {
    routeContact.x = 505;
    routeContact.y = 690;
    routeContact.z = terrainHeightAt(routeContact.x, routeContact.y) + 5;
    routeContact.routeIndex = 3;
    routeContact.confidence = Math.max(routeContact.confidence, 0.74);
    routeContact.latency = Math.min(routeContact.latency, 42);
  }

  const signal = sceneClassTargets.find((target) => target.id === "scene-signal-04");
  if (signal) {
    signal.confidence = Math.max(signal.confidence, 0.86);
    signal.latency = Math.min(signal.latency, 38);
  }

  pushLog("Incident: Unknown Contact Entered Route Corridor; Local C2 Took Authority.");
  const takeoverTasks = [
    ["uav-alpha", "patrol", { x: 560, y: 645 }],
    ["uav-bravo", "patrol", { x: 420, y: 610 }],
    ["uav-charlie", "hold", null],
    ["uav-delta", "patrol", { x: 790, y: 615 }],
  ];

  for (const [feedId, command, station] of takeoverTasks) {
    issueCommandToDrone(feedId, command);
    const feed = feeds.find((item) => item.id === feedId);
    if (feed && station) {
      feed.station = { ...station };
      feed.target = { ...station };
    }
  }
  localC2Incident.takeoverCommands = takeoverTasks.length;
  pushLog("Local C2 Takeover Complete: Swarm Retasked, Sync Gate Holding Commands.");
}

function maybeTriggerLocalC2Incident() {
  if (simTime >= DEMO_INCIDENT_TRIGGER_S) {
    triggerLocalC2Incident();
  }
}

function issueCommandToAll(command) {
  feeds.forEach((feed) => {
    const record = {
      id: `cmd-${String(commandSeq).padStart(3, "0")}`,
      assetId: feed.id,
      callsign: feed.callsign,
      command,
      mode: "fusion-local",
      status: "staged",
      ts: simTime,
    };
    commandSeq += 1;
    stagedCommands.unshift(record);

    const prevCommand = swarmTasking.lastCommand[feed.id];
    if (prevCommand && prevCommand.command !== command) {
      swarmTasking.retaskCount += 1;
    }
    swarmTasking.lastCommand[feed.id] = { command, ts: simTime };
    swarmTasking.history.unshift({ assetId: feed.id, callsign: feed.callsign, command, ts: simTime });
    swarmTasking.history.splice(20);

    if (command === "return") {
      feed.command = "return";
      feed.target = { ...BASE };
      feed.station = null;
    } else if (command === "hold") {
      feed.command = "hold";
    } else if (command === "patrol") {
      feed.command = "patrol";
      feed.station = { x: 680, y: 360 };
      feed.target = { ...feed.station };
    }
    pushLog(`[Bulk] ${feed.callsign} ${displayCommand(command)} Staged For Sync.`);
  });
  spoolDepth = stagedCommands.length;
  syncStaged = spoolDepth > 0;
  if (syncStaged) syncWatermark = simTime;
}

function movePlanarActor(actor, target, dt, cruiseSpeed, turnRateDeg) {
  const dx = target.x - actor.x;
  const dy = target.y - actor.y;
  const distance = Math.hypot(dx, dy);
  if (distance < 1) {
    actor.speed = approach(actor.speed || 0, 0, cruiseSpeed * dt);
    return distance;
  }
  const desiredHeading = Math.atan2(dy, dx);
  const currentHeading = (actor.heading * Math.PI) / 180;
  const maxTurn = ((turnRateDeg * Math.PI) / 180) * dt;
  const nextHeading = currentHeading + clamp(wrapAngle(desiredHeading - currentHeading), -maxTurn, maxTurn);
  actor.speed = approach(actor.speed || 0, cruiseSpeed, cruiseSpeed * 0.45 * dt);
  const step = Math.min(distance, actor.speed * dt);
  actor.x = clamp(actor.x + Math.cos(nextHeading) * step, 30, WORLD_M - 30);
  actor.y = clamp(actor.y + Math.sin(nextHeading) * step, 30, WORLD_M - 30);
  actor.heading = (nextHeading * 180) / Math.PI;
  return distance;
}

function moveAerialIngressContact(target, dt, cruiseSpeed, altitudeM, altitudePulse) {
  const path = target.ingressPath || [
    { x: 30, y: target.y },
    { x: WORLD_M * 0.5, y: WORLD_M * 0.5 },
    { x: WORLD_M - 30, y: target.y },
  ];
  target.routeIndex ??= 1;
  target.pathDirection ??= 1;
  const waypoint = path[target.routeIndex] || path[0];
  const distance = movePlanarActor(target, waypoint, dt, cruiseSpeed, 44);
  if (distance < 22) {
    let nextIndex = target.routeIndex + target.pathDirection;
    if (nextIndex < 0 || nextIndex >= path.length) {
      target.pathDirection *= -1;
      nextIndex = target.routeIndex + target.pathDirection;
    }
    target.routeIndex = clamp(nextIndex, 0, path.length - 1);
  }
  target.z = altitudeM + Math.sin(simTime * 1.15 + target.x * 0.01) * altitudePulse;
}

function updateFieldContacts(dt) {
  for (const target of sceneClassTargets) {
    target.freshness = clamp(target.freshness + Math.sin(simTime * 0.42 + target.x * 0.01) * 0.002, 0.62, 0.98);
    target.confidence = clamp(target.confidence + Math.cos(simTime * 0.36 + target.y * 0.01) * 0.002, 0.45, 0.92);
    target.latency = clamp(target.latency + Math.sin(simTime * 0.7 + target.heading) * 0.8, 24, 180);

    if (target.type === "vehicle") {
      const nextIndex = target.routeIndex ?? 0;
      const distance = movePlanarActor(target, ROUTE_GUARD_PATH[nextIndex], dt, 7, 42);
      if (distance < 24) {
        target.routeIndex = (nextIndex + 1) % ROUTE_GUARD_PATH.length;
      }
      target.z = terrainHeightAt(target.x, target.y) + 4;
    } else if (target.type === "rf-source") {
      target.originX ??= target.x;
      target.originY ??= target.y;
      target.driftPhase = (target.driftPhase || 0) + dt * 0.22;
      target.x = clamp(target.originX + Math.cos(target.driftPhase) * 18, 30, WORLD_M - 30);
      target.y = clamp(target.originY + Math.sin(target.driftPhase * 0.7) * 12, 30, WORLD_M - 30);
      target.heading = (target.heading + dt * 18) % 360;
      target.z = terrainHeightAt(target.x, target.y) + 3;
    } else if (target.type === "personnel") {
      const patrol = target.patrolPath || [{ x: target.x, y: target.y }];
      const nextIndex = target.patrolIndex ?? 0;
      const distance = movePlanarActor(target, patrol[nextIndex], dt, 1.4, 90);
      if (distance < 8) {
        target.patrolIndex = (nextIndex + 1) % patrol.length;
      }
      target.z = terrainHeightAt(target.x, target.y) + 2;
    } else if (target.type === "small-uas") {
      moveAerialIngressContact(target, dt, target.speed || 16, 76, 8);
    } else if (target.type === "unknown-contact") {
      const nextIndex = target.routeIndex ?? 0;
      const distance = movePlanarActor(target, ROUTE_GUARD_PATH[nextIndex], dt, 4.8, 35);
      if (distance < 16) {
        target.routeIndex = (nextIndex + 1) % ROUTE_GUARD_PATH.length;
      }
      target.z = terrainHeightAt(target.x, target.y) + 4;
    } else if (target.type === "unknown-uas") {
      moveAerialIngressContact(target, dt, target.speed || 14, 88, 7);
    }
  }
}

function stepSimulation(dt) {
  if (simPaused) return;
  simTime += dt;
  maybeTriggerLocalC2Incident();
  updateFieldContacts(dt);

  // drift feed quality metrics over time
  for (const feed of feeds) {
    feed.freshness = Math.max(0.4, Math.min(1.0, feed.freshness + (Math.random() - 0.5) * 0.02));
    feed.confidence = Math.max(0.3, Math.min(0.99, feed.confidence + (Math.random() - 0.5) * 0.03));
    feed.latency = Math.max(20, Math.min(300, feed.latency + (Math.random() - 0.5) * 10));
    if (feed.npu) {
      feed.npu.confidence = clamp(feed.npu.confidence + Math.sin(simTime * 0.31 + feed.x * 0.01) * 0.002, 0.52, 0.96);
    }
  }

  // Laptop battery drain (simulates fusion node power consumption)
  if (powerSource === "battery") {
    laptopBattery = Math.max(0, laptopBattery - BATTERY_DRAIN_RATE * dt);
  } else if (powerSource === "backpack_generator") {
    laptopBattery = Math.min(100, laptopBattery + dt * 0.5); // slow trickle charge
  }
  // CPU load fluctuates with workload
  cpuLoad = clamp(cpuLoad + (Math.random() - 0.48) * 2.5, 15, 98);

  for (const feed of feeds) {
    feed.battery = Math.max(35, feed.battery - dt * 0.018);
    if (feed.command === "hold") {
      brakeAsset(feed, dt);
      continue;
    }

    if (feed.command === "patrol" || feed.command === "relay" || feed.command === "overwatch" || feed.command === "scout") {
      feed.orbitPhase += dt * 0.22;
      if (!feed.station) feed.station = { ...feed.target };
      const center = feed.station;
      const radius = feed.command === "relay" ? 230 : feed.command === "overwatch" ? 150 : feed.command === "scout" ? 95 : 180;
      feed.target = {
        x: clamp(center.x + Math.cos(feed.orbitPhase) * radius, 70, WORLD_M - 70),
        y: clamp(center.y + Math.sin(feed.orbitPhase) * radius * 0.72, 70, WORLD_M - 70),
      };
    }

    const spatialHits = bvhQuery(feed);
    const rtDecision = planRtGeometryControl(feed, spatialHits);
    rememberRtControl(feed, rtDecision);
    feed.rtControl = rtDecision;
    const avoidance = rtDecision.hit?.kind === "hazard"
      ? rtDecision.hit
      : spatialHits.find((hit) => hit.kind === "hazard" && hit.distance < hit.radius + 35);
    const terrainConflict = spatialHits.find((hit) => hit.kind === "terrain" && hit.distance < hit.radius);
    const target = rtDecision.target || feed.target;
    moveToward(feed, target, dt, avoidance || terrainConflict);
  }
  updateFusedTracks(dt);
}

function planRtGeometryControl(feed, hits) {
  const backend = rtControlBackendLabel();
  if (feed.battery < 45) {
    return {
      command: "return",
      label: "Return On Reserve",
      shortLabel: "Return",
      priority: "Watch",
      backend,
      target: { ...BASE },
      hit: null,
    };
  }

  const criticalHazard = hits.find((hit) =>
    hit.kind === "hazard" && hit.severity === "critical" && hit.distance < hit.radius + 42,
  );
  if (criticalHazard) {
    return {
      command: "hold",
      label: `Avoid ${criticalHazard.label}`,
      shortLabel: "Avoid RF",
      priority: "Critical",
      backend,
      target: escapeTarget(feed, criticalHazard, 170),
      hit: criticalHazard,
    };
  }

  const unknownRouteContact = hits.find((hit) => hit.kind === "unknown" && hit.distance < 360);
  if (unknownRouteContact) {
    return {
      command: "patrol",
      label: `Standoff ${detectionClass(unknownRouteContact)}`,
      shortLabel: "Standoff",
      priority: "Critical",
      backend,
      target: escapeTarget(feed, unknownRouteContact, 130),
      hit: unknownRouteContact,
    };
  }

  const terrainClearance = hits.find((hit) => hit.kind === "terrain" && hit.distance < hit.radius);
  if (terrainClearance) {
    return {
      command: "patrol",
      label: "Terrain Clearance",
      shortLabel: "Clearance",
      priority: "Watch",
      backend,
      target: feed.target,
      hit: terrainClearance,
    };
  }

  return {
    command: "resume",
    label: "Corridor Guarded",
    shortLabel: "Guarded",
    priority: "Normal",
    backend,
    target: feed.target,
    hit: null,
  };
}

function escapeTarget(feed, source, distance) {
  const dx = feed.x - source.x;
  const dy = feed.y - source.y;
  const magnitude = Math.max(1, Math.hypot(dx, dy));
  return {
    x: clamp(feed.x + (dx / magnitude) * distance, 50, WORLD_M - 50),
    y: clamp(feed.y + (dy / magnitude) * distance, 50, WORLD_M - 50),
  };
}

function rememberRtControl(feed, decision) {
  const signature = `${decision.command}:${decision.shortLabel}`;
  if (feed.rtControlSignature === signature) return;
  feed.rtControlSignature = signature;
  if (simTime < 1 || decision.priority === "Normal") return;
  pushLog(`${feed.callsign} RT Control ${displayCommand(decision.command)} · ${decision.label}.`);
}

function moveToward(feed, target, dt, avoidance) {
  const dx = target.x - feed.x;
  const dy = target.y - feed.y;
  const distance = Math.hypot(dx, dy);
  if (distance < 1) {
    updateAltitude(feed, dt, avoidance);
    return;
  }

  const desiredHeading = Math.atan2(dy, dx);
  const currentHeading = (feed.heading * Math.PI) / 180;
  const limits = kinematicLimits(feed);
  const maxTurn = limits.turnRateRad * dt;
  const turn = clamp(wrapAngle(desiredHeading - currentHeading), -maxTurn, maxTurn);
  const nextHeading = currentHeading + turn;
  const targetSpeed = targetCruiseSpeed(feed, distance);
  feed.speed = approach(feed.speed, targetSpeed, limits.acceleration * dt);

  const step = Math.min(distance + 4, feed.speed * dt);
  feed.x += Math.cos(nextHeading) * step;
  feed.y += Math.sin(nextHeading) * step;
  feed.heading = (nextHeading * 180) / Math.PI;
  feed.x = clamp(feed.x, 40, WORLD_M - 40);
  feed.y = clamp(feed.y, 40, WORLD_M - 40);
  updateAltitude(feed, dt, avoidance);
}

function brakeAsset(feed, dt) {
  const limits = kinematicLimits(feed);
  feed.speed = approach(feed.speed, 0, limits.deceleration * dt);
  const heading = (feed.heading * Math.PI) / 180;
  feed.x += Math.cos(heading) * feed.speed * dt;
  feed.y += Math.sin(heading) * feed.speed * dt;
  feed.x = clamp(feed.x, 40, WORLD_M - 40);
  feed.y = clamp(feed.y, 40, WORLD_M - 40);
  updateAltitude(feed, dt, null);
}

function kinematicLimits(feed) {
  if (feed.type === "fixed-wing") {
    return {
      acceleration: 7,
      deceleration: 5,
      turnRateRad: (48 * Math.PI) / 180,
      climbRate: 5,
    };
  }
  return {
    acceleration: 11,
    deceleration: 13,
    turnRateRad: (118 * Math.PI) / 180,
    climbRate: 9,
  };
}

function targetCruiseSpeed(feed, distance) {
  const cruise = feed.cruiseSpeed || feed.speed || 24;
  if (feed.type === "fixed-wing") {
    return Math.max(20, Math.min(cruise, distance * 0.18));
  }
  return Math.max(4, Math.min(cruise, distance * 0.22));
}

function updateAltitude(feed, dt, avoidance) {
  const limits = kinematicLimits(feed);
  const terrain = terrainHeightAt(feed.x, feed.y);
  const patrolWave = Math.sin(simTime * 0.75 + feed.orbitPhase) * 5;
  const avoidanceLift = avoidance ? 18 : 0;
  const commandBias = feed.command === "return" ? -10 : feed.command === "overwatch" ? 16 : 0;
  const targetAltitude = clamp(
    terrain + (feed.cruiseAltitude || feed.z) + patrolWave + avoidanceLift + commandBias,
    80,
    280,
  );
  feed.z = approach(feed.z, targetAltitude, limits.climbRate * dt);
}

function approach(value, target, maxDelta) {
  if (value < target) return Math.min(target, value + maxDelta);
  return Math.max(target, value - maxDelta);
}

function bvhQuery(asset) {
  const hits = [];
  const terrainClearance = asset.z - terrainHeightAt(asset.x, asset.y);
  if (terrainClearance < 82) {
    hits.push({
      id: "terrain-clearance",
      label: "Terrain Clearance",
      kind: "terrain",
      severity: "watch",
      distance: Math.max(0, terrainClearance),
      radius: 82,
      x: asset.x,
      y: asset.y,
    });
  }
  for (const hazard of hazards) {
    const distance = Math.hypot(asset.x - hazard.x, asset.y - hazard.y);
    if (distance < hazard.r + 90) {
      hits.push({ ...hazard, kind: "hazard", distance, radius: hazard.r });
    }
  }
  for (const contact of sceneClassTargets.filter((item) => item.type.startsWith("unknown"))) {
    const routeDistance = distanceToRouteGuard(contact);
    const contactDistance = Math.hypot(asset.x - contact.x, asset.y - contact.y);
    if (routeDistance < ROUTE_GUARD_HALF_WIDTH_M + 24 && contactDistance < 360) {
      hits.push({
        ...contact,
        label: "Unknown Route Contact",
        kind: "unknown",
        severity: "critical",
        distance: contactDistance,
        radius: 34,
      });
    }
  }
  for (const other of allFeeds()) {
    if (other.id === asset.id) continue;
    const distance = Math.hypot(asset.x - other.x, asset.y - other.y);
    if (distance < 155) {
      hits.push({ ...other, kind: "asset", distance, radius: 28 });
    }
  }
  return hits.sort((a, b) => a.distance - b.distance);
}

function distanceToRouteGuard(point) {
  let minDistance = Infinity;
  for (let index = 0; index < ROUTE_GUARD_PATH.length - 1; index += 1) {
    minDistance = Math.min(
      minDistance,
      distancePointToSegment(point, ROUTE_GUARD_PATH[index], ROUTE_GUARD_PATH[index + 1]),
    );
  }
  return minDistance;
}

function distancePointToSegment(point, a, b) {
  const vx = b.x - a.x;
  const vy = b.y - a.y;
  const wx = point.x - a.x;
  const wy = point.y - a.y;
  const lengthSq = vx * vx + vy * vy;
  if (lengthSq === 0) return Math.hypot(point.x - a.x, point.y - a.y);
  const t = clamp((wx * vx + wy * vy) / lengthSq, 0, 1);
  const x = a.x + t * vx;
  const y = a.y + t * vy;
  return Math.hypot(point.x - x, point.y - y);
}

function buildBvhNodes() {
  return hazards.map((hazard) => ({
    x: hazard.x - hazard.r,
    y: hazard.y - hazard.r,
    w: hazard.r * 2,
    h: hazard.r * 2,
    severity: hazard.severity,
  }));
}

function modeCopy() {
  return {
    sync: stagedCommands.length,
    watermark: syncWatermark,
  };
}

function syncGateLabel() {
  if (connectivityMode === "online") return spoolDepth > 0 ? `${spoolDepth} Releasable` : "Open";
  if (connectivityMode === "degraded") return spoolDepth > 0 ? `${spoolDepth} Queued` : "Queued Local";
  return spoolDepth > 0 ? `${spoolDepth} Held` : "Closed Local";
}

function classifyFrame(feed, visible) {
  const objectCount = visible.length;
  const airCount = visible.filter((obj) => obj.type !== "ground").length;
  const vehicleCount = visible.filter((obj) => obj.type === "vehicle").length;
  const unknownCount = visible.filter((obj) => obj.type.startsWith("unknown")).length;
  const avgConfidence = objectCount
    ? visible.reduce((sum, obj) => sum + obj.detectionConfidence, 0) / objectCount
    : 0;
  const modelRows = classifierCueRows();
  if (modelRows?.length) {
    return modelRows;
  }
  if (unknownCount > 0) {
    return [
      ["Unknown Contact Requires ID", 0.9],
      ["Distributed NPU Cue Pass", Math.max(0.52, feed.npu?.confidence || avgConfidence)],
      [vehicleCount ? "Four-Wheeled Vehicle Frames" : "Corridor Geometry Check", vehicleCount ? clamp(vehicleCount / 3, 0.34, 0.94) : 0.88],
    ];
  }
  if (vehicleCount > 0) {
    return [
      ["Four-Wheeled Vehicle Frames", clamp(vehicleCount / 3, 0.34, 0.94)],
      ["Objects Quantified", Math.max(0.55, avgConfidence)],
      ["Range And Altitude Labels", objectCount ? 0.91 : 0.12],
    ];
  }
  if (visible.some((obj) => obj.threat === "critical")) {
    return [
      ["Restricted Object Quantified", 0.92],
      ["Objects Quantified", Math.max(0.48, avgConfidence)],
      ["Air Tracks Detected", clamp(airCount / Math.max(1, feeds.length), 0.16, 0.98)],
    ];
  }
  if (feed.battery < 70) {
    return [
      ["Low Power Track Quantified", 0.84],
      ["Objects Quantified", Math.max(0.45, avgConfidence)],
      ["Air Tracks Detected", clamp(airCount / Math.max(1, feeds.length), 0.16, 0.98)],
    ];
  }
  return [
    ["Objects Quantified", Math.max(0.55, avgConfidence)],
    ["Air Tracks Detected", clamp(airCount / Math.max(1, feeds.length), 0.16, 0.98)],
    ["Range And Altitude Labels", objectCount ? 0.91 : 0.12],
  ];
}

function updateFusedTracks(dt) {
  void dt;
  const observedTracks = new Set();

  for (const feed of feeds) {
    for (const observation of detectObjectsForFeed(feed)) {
      const track = upsertFusedTrack(feed, observation);
      observedTracks.add(track.id);
    }
  }

  for (const [trackId, track] of fusedTracks) {
    if (!observedTracks.has(trackId)) {
      track.sources.clear();
    }
    if (simTime - track.lastSeen > TRACK_PRUNE_SECONDS) {
      fusedTracks.delete(trackId);
      if (selectedContactId === trackId) selectedContactId = null;
    }
  }
}

function upsertFusedTrack(feed, observation) {
  const trackId = associateTrack(observation);
  const existing = trackId ? fusedTracks.get(trackId) : null;
  const track = existing || {
    id: `track-${nextTrackSerial++}`,
    targetId: observation.id,
    firstSeen: simTime,
    lastSeen: simTime,
    x: observation.x,
    y: observation.y,
    z: observation.z,
    vx: 0,
    vy: 0,
    vz: 0,
    key: observation.key,
    callsign: observation.callsign,
    type: observation.type,
    className: observation.className,
    trainingClass: observation.trainingClass,
    classifierCue: observation.classifierCue,
    confidence: observation.detectionConfidence,
    threat: observation.threat,
    affiliation: observation.affiliation,
    identityKnown: observation.identityKnown,
    sources: new Set(),
    history: [],
  };

  const elapsed = Math.max(0.001, simTime - track.lastSeen);
  track.vx = (observation.x - track.x) / elapsed;
  track.vy = (observation.y - track.y) / elapsed;
  track.vz = (observation.z - track.z) / elapsed;
  track.x = observation.x;
  track.y = observation.y;
  track.z = observation.z;
  track.key = observation.key;
  track.callsign = observation.callsign;
  track.type = observation.type;
  track.className = observation.className;
  track.trainingClass = observation.trainingClass;
  track.classifierCue = observation.classifierCue;
  track.confidence = Math.max(track.confidence * 0.72, observation.detectionConfidence);
  track.threat = observation.threat === "critical" ? "critical" : track.threat;
  track.affiliation = observation.affiliation;
  track.identityKnown = observation.identityKnown;
  track.lastSeen = simTime;
  track.sources.add(feed.callsign);
  track.history.unshift({
    source: feed.callsign,
    confidence: observation.detectionConfidence,
    ts: simTime,
  });
  track.history = track.history.slice(0, 10);
  fusedTracks.set(track.id, track);
  return track;
}

function associateTrack(observation) {
  for (const [trackId, track] of fusedTracks) {
    if (track.targetId === observation.id) return trackId;
  }

  let nearestId = null;
  let nearestDistance = TRACK_ASSOCIATION_RADIUS_M;
  for (const [trackId, track] of fusedTracks) {
    if (track.type !== observation.type) continue;
    const distance = Math.hypot(track.x - observation.x, track.y - observation.y);
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearestId = trackId;
    }
  }
  return nearestId;
}

function fusedTrackObjects(feed) {
  void feed;
  const fused = [];
  const reference = FIELD_VIEW_ANCHOR;

  for (const track of fusedTracks.values()) {
    const age = simTime - track.lastSeen;
    if (age > TRACK_MEMORY_SECONDS) continue;
    const dx = track.x - reference.x;
    const dy = track.y - reference.y;
    const range = Math.round(Math.hypot(dx, dy));
    const angle = Math.atan2(dy, dx);
    const delta = wrapAngle(angle);
    const liveSources = Array.from(track.sources);
    const sourceNames = liveSources.length
      ? liveSources
      : track.history.slice(0, 4).map((item) => item.source);
    fused.push({
      id: track.id,
      targetId: track.targetId,
      callsign: track.callsign,
      x: track.x,
      y: track.y,
      z: track.z,
      vx: track.vx,
      vy: track.vy,
      type: track.type,
      key: track.key,
      className: track.className,
      trainingClass: track.trainingClass,
      classifierCue: track.classifierCue,
      range,
      bearingDeg: Math.round(((delta * 180) / Math.PI + 360) % 360),
      altitudeDelta: Math.round(track.z - reference.z),
      detectionConfidence: clamp(track.confidence - age * 0.012, 0.38, 0.98),
      threat: track.threat,
      affiliation: track.affiliation,
      identityKnown: track.identityKnown,
      trackAge: age,
      trackStatus: liveSources.length ? "live" : "memory",
      trackSources: sourceNames,
      observationCount: track.history.length,
    });
  }

  return fused.sort((a, b) => {
    const threatDelta = (b.threat === "critical") - (a.threat === "critical");
    if (threatDelta) return threatDelta;
    const statusDelta = (a.trackStatus === "live" ? 0 : 1) - (b.trackStatus === "live" ? 0 : 1);
    if (statusDelta) return statusDelta;
    return a.range - b.range;
  });
}

function visibleObjects(feed) {
  return fusedTrackObjects(feed);
}

function detectObjectsForFeed(feed) {
  const objects = [];
  const detectionRangeM = 650;
  for (const target of detectableObjects()) {
    if (target.id === feed.id) continue;
    const dx = target.x - feed.x;
    const dy = target.y - feed.y;
    const distance = Math.hypot(dx, dy);
    if (distance > detectionRangeM) continue;
    const angle = Math.atan2(dy, dx);
    const heading = (feed.heading * Math.PI) / 180;
    const delta = wrapAngle(angle - heading);
    const friendly = isKnownFriendly(target);
    const unknownInCorridor = !friendly
      && target.type.startsWith("unknown")
      && distanceToRouteGuard(target) <= ROUTE_GUARD_HALF_WIDTH_M + 24;
    const threat = friendly
      ? "friendly"
      : unknownInCorridor || bvhQuery(target).some((hit) => hit.severity === "critical" && hit.distance < hit.radius)
      ? "critical"
      : "watch";
    const detectionConfidence = friendly
      ? clamp(target.confidence * 0.5 + target.freshness * 0.35 + 0.14 - distance / 7000, 0.88, 0.99)
      : clamp(
          target.confidence * 0.5 + target.freshness * 0.2 + (feed.npu?.confidence || 0.7) * 0.22 + (target.type === "ground" ? 0.04 : 0.08) - distance / 3000,
          0.45,
          0.98,
        );
    objects.push({
      ...target,
      range: Math.round(distance),
      bearingDeg: Math.round(((delta * 180) / Math.PI + 360) % 360),
      altitudeDelta: Math.round(target.z - feed.z),
      className: detectionClass(target),
      detectionConfidence,
      threat,
      affiliation: friendly ? "friendly" : "unresolved",
      identityKnown: friendly,
    });
  }
  return objects.sort((a, b) => a.range - b.range);
}

function resizeCanvas(canvas) {
  const bounds = canvas.parentElement.getBoundingClientRect();
  canvas.width = Math.max(480, Math.floor(bounds.width));
  canvas.height = Math.max(340, Math.floor(bounds.height));
}

function worldViewport(width, height) {
  const scale = Math.min(width, height) / WORLD_M;
  const size = WORLD_M * scale;
  return {
    scale,
    size,
    x: (width - size) / 2,
    y: (height - size) / 2,
  };
}

function worldToCanvas(asset, width, height) {
  const viewport = worldViewport(width, height);
  return {
    x: viewport.x + asset.x * viewport.scale,
    y: viewport.y + asset.y * viewport.scale,
  };
}

function worldMetersToCanvas(meters, width, height) {
  return meters * worldViewport(width, height).scale;
}

function worldRectToCanvas(rect, width, height) {
  const viewport = worldViewport(width, height);
  const origin = worldToCanvas(rect, width, height);
  return {
    x: origin.x,
    y: origin.y,
    w: rect.w * viewport.scale,
    h: rect.h * viewport.scale,
  };
}

function terrainHeightAt(x, y) {
  const ridge = Math.sin(x * 0.011 + y * 0.004) * 22;
  const basin = Math.cos(x * 0.006 - y * 0.009) * 14;
  const roughness = Math.sin((x + y) * 0.024) * 6;
  return clamp(38 + ridge + basin + roughness, 4, 92);
}

function terrainTriangleCount() {
  const cells = Math.ceil(WORLD_M / AOI_TILE.meshStepM);
  return cells * cells * 2;
}

function drawTerrainBackdrop(ctx, width, height) {
  drawProceduralTerrain(ctx, width, height);
  drawLocalGrid(ctx, width, height);
  drawContourOverlay(ctx, width, height);
  drawTerrainMesh(ctx, width, height);
  drawScaleBar(ctx, width, height);
}

function drawProceduralTerrain(ctx, width, height) {
  const terrain = ctx.createLinearGradient(0, 0, width, height);
  terrain.addColorStop(0, "#1c2a2a");
  terrain.addColorStop(0.34, "#273424");
  terrain.addColorStop(0.68, "#17261f");
  terrain.addColorStop(1, "#0c1415");
  ctx.fillStyle = terrain;
  ctx.fillRect(0, 0, width, height);

  ctx.fillStyle = "rgba(121,184,255,0.06)";
  ctx.beginPath();
  ctx.moveTo(width * 0.08, height * 0.88);
  ctx.bezierCurveTo(width * 0.22, height * 0.68, width * 0.34, height * 0.62, width * 0.48, height * 0.44);
  ctx.bezierCurveTo(width * 0.62, height * 0.26, width * 0.78, height * 0.18, width * 0.94, height * 0.08);
  ctx.lineTo(width, height * 0.16);
  ctx.bezierCurveTo(width * 0.8, height * 0.3, width * 0.65, height * 0.38, width * 0.5, height * 0.58);
  ctx.bezierCurveTo(width * 0.35, height * 0.78, width * 0.2, height * 0.86, width * 0.08, height);
  ctx.closePath();
  ctx.fill();
}

function drawLocalGrid(ctx, width, height) {
  const viewport = worldViewport(width, height);
  const left = viewport.x;
  const right = viewport.x + viewport.size;
  const top = viewport.y;
  const bottom = viewport.y + viewport.size;
  ctx.save();
  ctx.strokeStyle = "rgba(245,241,232,0.08)";
  ctx.lineWidth = 1;
  for (let meters = 0; meters <= WORLD_M; meters += 150) {
    const x = worldToCanvas({ x: meters, y: 0 }, width, height).x;
    const y = worldToCanvas({ x: 0, y: meters }, width, height).y;
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, bottom);
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
  }

  ctx.strokeStyle = "rgba(85,214,166,0.28)";
  ctx.lineWidth = 1.4;
  for (let meters = 0; meters <= WORLD_M; meters += 300) {
    const x = worldToCanvas({ x: meters, y: 0 }, width, height).x;
    const y = worldToCanvas({ x: 0, y: meters }, width, height).y;
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, bottom);
    ctx.moveTo(left, y);
    ctx.lineTo(right, y);
    ctx.stroke();
  }
  ctx.fillStyle = "rgba(245,241,232,0.68)";
  ctx.font = "11px Inter, Arial";
  ctx.fillText("Local Meters", left + 16, bottom - 18);
  ctx.restore();
}

function drawContourOverlay(ctx, width, height) {
  ctx.save();
  for (let band = 0; band < 12; band += 1) {
    const y = height * (0.12 + band * 0.075);
    ctx.strokeStyle = band % 3 === 0 ? "rgba(230,195,92,0.16)" : "rgba(245,241,232,0.08)";
    ctx.lineWidth = band % 3 === 0 ? 1.4 : 1;
    ctx.beginPath();
    for (let x = -20; x <= width + 20; x += 28) {
      const wave = Math.sin(x * 0.012 + band * 0.9) * height * 0.028;
      const ridge = y + wave + Math.cos(x * 0.006 + band) * height * 0.018;
      if (x === -20) ctx.moveTo(x, ridge);
      else ctx.lineTo(x, ridge);
    }
    ctx.stroke();
  }
  ctx.restore();
}

function drawEarthAoiTile(ctx, image, width, height) {
  const cropW = image.naturalWidth * AOI_TILE.cropScale;
  const cropH = cropW * (height / width);
  const sx = clamp(image.naturalWidth * AOI_TILE.cropX - cropW / 2, 0, image.naturalWidth - cropW);
  const sy = clamp(image.naturalHeight * AOI_TILE.cropY - cropH / 2, 0, image.naturalHeight - cropH);
  ctx.drawImage(image, sx, sy, cropW, cropH, 0, 0, width, height);
}

function projectTerrainPoint(x, y, width, height) {
  const p = worldToCanvas({ x, y }, width, height);
  return {
    x: p.x,
    y: p.y - terrainHeightAt(x, y) * 0.22,
  };
}

function drawTerrainMesh(ctx, width, height) {
  ctx.save();
  ctx.globalAlpha = 0.5;
  ctx.strokeStyle = "rgba(245,241,232,0.13)";
  ctx.lineWidth = 1;
  for (let grid = 0; grid <= WORLD_M; grid += AOI_TILE.meshStepM) {
    ctx.beginPath();
    for (let x = 0; x <= WORLD_M; x += AOI_TILE.meshStepM / 2) {
      const p = projectTerrainPoint(x, grid, width, height);
      if (x === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    }
    ctx.stroke();

    ctx.beginPath();
    for (let y = 0; y <= WORLD_M; y += AOI_TILE.meshStepM / 2) {
      const p = projectTerrainPoint(grid, y, width, height);
      if (y === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    }
    ctx.stroke();
  }
  ctx.restore();
}

function drawScaleBar(ctx, width, height) {
  const viewport = worldViewport(width, height);
  const scaleM = 300;
  const barW = worldMetersToCanvas(scaleM, width, height);
  const x = viewport.x + viewport.size - barW - 28;
  const y = viewport.y + viewport.size - 28;
  ctx.save();
  ctx.strokeStyle = "rgba(245,241,232,0.82)";
  ctx.fillStyle = "rgba(8,13,15,0.72)";
  ctx.lineWidth = 2;
  ctx.fillRect(x - 10, y - 22, barW + 20, 34);
  ctx.beginPath();
  ctx.moveTo(x, y);
  ctx.lineTo(x + barW, y);
  ctx.moveTo(x, y - 6);
  ctx.lineTo(x, y + 6);
  ctx.moveTo(x + barW, y - 6);
  ctx.lineTo(x + barW, y + 6);
  ctx.stroke();
  ctx.fillStyle = "#f5f1e8";
  ctx.font = "12px Inter, Arial";
  ctx.fillText(`${scaleM} m`, x + barW / 2 - 18, y - 9);
  ctx.fillText("1.2 km x 1.2 km AOI", x - 2, y + 22);
  ctx.restore();
}

function drawImageCover(ctx, image, width, height) {
  const imageRatio = image.naturalWidth / image.naturalHeight;
  const canvasRatio = width / height;
  let sx = 0;
  let sy = 0;
  let sw = image.naturalWidth;
  let sh = image.naturalHeight;

  if (imageRatio > canvasRatio) {
    sw = image.naturalHeight * canvasRatio;
    sx = (image.naturalWidth - sw) / 2;
  } else {
    sh = image.naturalWidth / canvasRatio;
    sy = (image.naturalHeight - sh) / 2;
  }

  ctx.drawImage(image, sx, sy, sw, sh, 0, 0, width, height);
}

function drawRoadNetwork(ctx, width, height) {
  ctx.strokeStyle = "rgba(245,241,232,0.26)";
  ctx.lineWidth = 1.4;
  ctx.beginPath();
  drawWorldPath(
    ctx,
    [
      { x: 215, y: 1128 },
      { x: 435, y: 792 },
      { x: 696, y: 672 },
    ],
    width,
    height,
  );
  ctx.stroke();
}

function routeSegmentOffset(a, b, offsetM) {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const length = Math.max(1, Math.hypot(dx, dy));
  const nx = (-dy / length) * offsetM;
  const ny = (dx / length) * offsetM;
  return {
    a: { x: a.x + nx, y: a.y + ny },
    b: { x: b.x + nx, y: b.y + ny },
  };
}

function drawWorldPath(ctx, points, width, height) {
  points.forEach((point, index) => {
    const projected = worldToCanvas(point, width, height);
    if (index === 0) ctx.moveTo(projected.x, projected.y);
    else ctx.lineTo(projected.x, projected.y);
  });
}

function drawRouteGuardCorridor2D(ctx, width, height) {
  const corridorPx = worldMetersToCanvas(ROUTE_GUARD_HALF_WIDTH_M * 2, width, height);
  ctx.save();
  ctx.lineCap = "round";
  ctx.lineJoin = "round";

  ctx.strokeStyle = "rgba(85, 214, 166, 0.1)";
  ctx.lineWidth = corridorPx;
  ctx.beginPath();
  drawWorldPath(ctx, ROUTE_GUARD_PATH, width, height);
  ctx.stroke();

  for (const offset of [-ROUTE_GUARD_HALF_WIDTH_M, ROUTE_GUARD_HALF_WIDTH_M]) {
    ctx.strokeStyle = "rgba(85, 214, 166, 0.7)";
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    for (let index = 0; index < ROUTE_GUARD_PATH.length - 1; index += 1) {
      const segment = routeSegmentOffset(ROUTE_GUARD_PATH[index], ROUTE_GUARD_PATH[index + 1], offset);
      const a = worldToCanvas(segment.a, width, height);
      const b = worldToCanvas(segment.b, width, height);
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
    }
    ctx.stroke();
  }

  ctx.strokeStyle = "rgba(230, 195, 92, 0.76)";
  ctx.lineWidth = 2.6;
  ctx.setLineDash([16, 10]);
  ctx.beginPath();
  drawWorldPath(ctx, ROUTE_GUARD_PATH, width, height);
  ctx.stroke();
  ctx.setLineDash([]);

  const labelPoint = worldToCanvas(ROUTE_GUARD_PATH[2], width, height);
  ctx.fillStyle = "rgba(8, 13, 15, 0.76)";
  ctx.fillRect(labelPoint.x - 10, labelPoint.y - 28, 132, 22);
  ctx.fillStyle = "#55d6a6";
  ctx.font = "12px Inter, Arial";
  ctx.fillText("Route Guard Corridor", labelPoint.x - 2, labelPoint.y - 12);
  ctx.restore();
}

function drawSwarmMap() {
  resizeCanvas(swarmCanvas);
  const width = swarmCanvas.width;
  const height = swarmCanvas.height;
  const ctx = swarmCtx;
  ctx.clearRect(0, 0, width, height);
  drawTerrainBackdrop(ctx, width, height);
  drawRoadNetwork(ctx, width, height);
  drawRouteGuardCorridor2D(ctx, width, height);

  for (const node of buildBvhNodes()) {
    const rect = worldRectToCanvas(node, width, height);
    ctx.strokeStyle = node.severity === "critical" ? "rgba(255, 93, 93, 0.42)" : "rgba(230, 195, 92, 0.35)";
    ctx.lineWidth = 1;
    ctx.strokeRect(rect.x, rect.y, rect.w, rect.h);
  }

  for (const hazard of hazards) {
    const point = worldToCanvas(hazard, width, height);
    drawZone(ctx, point.x, point.y, worldMetersToCanvas(hazard.r, width, height), hazard.severity === "critical" ? "#6d3238" : "#65551f", hazard.label);
  }

  drawBase(ctx, width, height);
  for (const feed of feeds) {
    drawPath(ctx, feed, width, height);
  }
  for (const asset of allFeeds()) {
    drawAsset(ctx, asset, width, height);
  }
  for (const contact of sceneClassTargets) {
    drawFieldContact(ctx, contact, width, height);
  }
  drawRayFan(ctx, selectedFeed(), width, height);
}

function drawBase(ctx, width, height) {
  const point = worldToCanvas(BASE, width, height);
  ctx.fillStyle = "#d8e0dc";
  ctx.strokeStyle = "#10171b";
  ctx.lineWidth = 2;
  ctx.fillRect(point.x - 12, point.y - 12, 24, 24);
  ctx.strokeRect(point.x - 12, point.y - 12, 24, 24);
  ctx.fillStyle = "#f2efe5";
  ctx.font = "12px Inter, Arial";
  drawCanvasLabel(ctx, "Fusion Node", point.x + 16, point.y + 4, width, height);
}

function drawPath(ctx, feed, width, height) {
  if (!feed.target) return;
  const start = worldToCanvas(feed, width, height);
  const end = worldToCanvas(feed.target, width, height);
  ctx.strokeStyle = feed.id === selectedId ? "rgba(85, 214, 166, 0.64)" : "rgba(121, 184, 255, 0.22)";
  ctx.setLineDash([5, 5]);
  ctx.beginPath();
  ctx.moveTo(start.x, start.y);
  ctx.lineTo(end.x, end.y);
  ctx.stroke();
  ctx.setLineDash([]);
}

function drawRayFan(ctx, feed, width, height) {
  const origin = worldToCanvas(feed, width, height);
  const heading = (feed.heading * Math.PI) / 180;
  ctx.strokeStyle = "rgba(85, 214, 166, 0.28)";
  ctx.lineWidth = 1;
  for (let i = -2; i <= 2; i += 1) {
    const angle = heading + i * 0.18;
    ctx.beginPath();
    ctx.moveTo(origin.x, origin.y);
    ctx.lineTo(origin.x + Math.cos(angle) * width * 0.22, origin.y + Math.sin(angle) * height * 0.22);
    ctx.stroke();
  }
}

function drawWheeledVehicleGlyph(ctx, x, y, headingDeg, scale = 1) {
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate((headingDeg * Math.PI) / 180);
  ctx.beginPath();
  ctx.rect(-14 * scale, -7 * scale, 28 * scale, 14 * scale);
  ctx.fill();
  ctx.stroke();

  ctx.fillStyle = "rgba(8, 13, 15, 0.92)";
  for (const wheel of [
    [-10, -8],
    [10, -8],
    [-10, 8],
    [10, 8],
  ]) {
    ctx.beginPath();
    ctx.ellipse(wheel[0] * scale, wheel[1] * scale, 3.2 * scale, 2.1 * scale, 0, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.fillStyle = "rgba(245, 241, 232, 0.28)";
  ctx.fillRect(-3 * scale, -5 * scale, 9 * scale, 10 * scale);
  ctx.restore();
}

function drawAsset(ctx, asset, width, height) {
  const { x, y } = worldToCanvas(asset, width, height);
  const color = colors[asset.key] || "#f2efe5";
  const selected = asset.id === selectedId;
  ctx.save();
  if (selected) {
    ctx.strokeStyle = "rgba(245, 241, 232, 0.82)";
    ctx.lineWidth = 2;
    ctx.setLineDash([4, 5]);
    ctx.strokeRect(x - 18, y - 18, 36, 36);
    ctx.setLineDash([]);
  }
  drawPlatformGlyph(ctx, x, y, asset, color, selected);
  ctx.fillStyle = "#f2efe5";
  ctx.font = "12px Inter, Arial";
  drawCanvasLabel(ctx, asset.callsign, x + 12, y + 4, width, height);
  ctx.restore();
}

function drawCanvasLabel(ctx, text, x, y, width, height) {
  const textWidth = ctx.measureText(text).width;
  ctx.fillText(text, clamp(x, 8, width - textWidth - 8), clamp(y, 14, height - 8));
}

function drawPlatformGlyph(ctx, x, y, asset, color, selected = false) {
  const heading = ((asset.heading || 0) * Math.PI) / 180;
  ctx.save();
  ctx.translate(x, y);
  ctx.rotate(heading);
  ctx.fillStyle = color;
  ctx.strokeStyle = selected ? "#f2efe5" : "rgba(8, 13, 15, 0.94)";
  ctx.lineWidth = selected ? 2.2 : 1.6;

  if (asset.type === "fixed-wing") {
    ctx.beginPath();
    ctx.moveTo(14, 0);
    ctx.lineTo(-10, -8);
    ctx.lineTo(-5, 0);
    ctx.lineTo(-10, 8);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
  } else if (asset.type === "ground") {
    ctx.beginPath();
    ctx.rect(-10, -6, 20, 12);
    ctx.fill();
    ctx.stroke();
  } else {
    ctx.beginPath();
    ctx.moveTo(-12, 0);
    ctx.lineTo(12, 0);
    ctx.moveTo(0, -12);
    ctx.lineTo(0, 12);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(0, -6);
    ctx.lineTo(6, 0);
    ctx.lineTo(0, 6);
    ctx.lineTo(-6, 0);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    for (const tick of [-12, 12]) {
      ctx.beginPath();
      ctx.moveTo(tick, -4);
      ctx.lineTo(tick, 4);
      ctx.moveTo(-4, tick);
      ctx.lineTo(4, tick);
      ctx.stroke();
    }
  }
  ctx.restore();
}

function drawFieldContact(ctx, contact, width, height) {
  const { x, y } = worldToCanvas(contact, width, height);
  const color = colors[contact.key] || "#55d6a6";
  ctx.save();
  ctx.fillStyle = color;
  ctx.strokeStyle = contact.type === "rf-source" ? "#ff5d5d" : "rgba(245, 241, 232, 0.78)";
  ctx.lineWidth = 1.6;
  if (contact.type === "vehicle") {
    drawWheeledVehicleGlyph(ctx, x, y, contact.heading || 0, 0.72);
    ctx.fillStyle = "#f2efe5";
    ctx.font = "11px Inter, Arial";
    drawCanvasLabel(ctx, contact.callsign, x + 15, y + 4, width, height);
    ctx.restore();
    return;
  }
  ctx.beginPath();
  if (contact.type === "unknown-contact") {
    ctx.moveTo(x, y - 8);
    ctx.lineTo(x + 8, y);
    ctx.lineTo(x, y + 8);
    ctx.lineTo(x - 8, y);
    ctx.closePath();
  } else if (contact.type === "unknown-uas") {
    ctx.moveTo(x, y - 9);
    ctx.lineTo(x + 9, y + 7);
    ctx.lineTo(x - 9, y + 7);
    ctx.closePath();
  } else if (contact.type === "personnel") {
    ctx.arc(x - 4, y, 3.5, 0, Math.PI * 2);
    ctx.moveTo(x + 7.5, y);
    ctx.arc(x + 4, y, 3.5, 0, Math.PI * 2);
  } else if (contact.type === "small-uas") {
    ctx.moveTo(x, y - 8);
    ctx.lineTo(x + 8, y + 6);
    ctx.lineTo(x - 8, y + 6);
    ctx.closePath();
  } else if (contact.type === "rf-source") {
    ctx.moveTo(x, y - 8);
    ctx.lineTo(x + 8, y);
    ctx.lineTo(x, y + 8);
    ctx.lineTo(x - 8, y);
    ctx.closePath();
  } else {
    ctx.arc(x, y, 6, 0, Math.PI * 2);
  }
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#f2efe5";
  ctx.font = "11px Inter, Arial";
  drawCanvasLabel(ctx, contact.callsign, x + 11, y + 4, width, height);
  ctx.restore();
}

function drawZone(ctx, x, y, radius, color, label) {
  ctx.fillStyle = `${color}66`;
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(x, y, radius, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#f2efe5";
  ctx.font = "12px Inter, Arial";
  ctx.fillText(label, x - radius + 10, y - radius + 18);
}

function drawPov(feed, visible) {
  resizeCanvas(povCanvas);
  const width = povCanvas.width;
  const height = povCanvas.height;
  drawPovMapBackground(width, height);
  drawPov3DGrid(feed, width, height);
  drawPovRouteGuardCorridor(feed, width, height);
  drawPovHazards(feed, width, height);
  drawPovDetectionFrustum(feed, width, height);
  drawPovObjects(feed, visible, width, height);
  drawPovTelemetry(feed, visible, width, height);
  drawPovQuantificationPanel(visible, width, height);
}

function detectionClass(asset) {
  const friendly = knownFriendlyFor(asset);
  if (friendly) return `${friendly.callsign} Friendly`;
  if (asset.type === "unknown-contact") return "Unknown Ground Contact";
  if (asset.type === "unknown-uas") return "Unknown Air Contact";
  if (asset.type === "vehicle") return "Wheeled Vehicle";
  if (asset.type === "rf-source") return "RF Source";
  if (asset.type === "personnel") return "Personnel";
  if (asset.type === "small-uas") return "Small UAS";
  if (asset.type === "ground") return "Ground Team";
  if (asset.type === "fixed-wing") return "Fixed Wing";
  return "Quadrotor";
}

function mapProjectionScale(width, height) {
  return Math.min(width, height) / 975;
}

function projectPovMapPoint(feed, point, width, height, zRelativeM = 0) {
  void feed;
  const scale = mapProjectionScale(width, height) * fieldView.zoom;
  const dx = point.x - FIELD_VIEW_ANCHOR.x;
  const dy = point.y - FIELD_VIEW_ANCHOR.y;
  const cameraYaw = fieldView.yaw;
  const cos = Math.cos(cameraYaw);
  const sin = Math.sin(cameraYaw);
  const rotatedX = dx * cos - dy * sin;
  const rotatedY = dx * sin + dy * cos;
  return {
    x: width * 0.5 + (rotatedX - rotatedY) * scale * 0.66,
    y: height * 0.58 + (rotatedX + rotatedY) * scale * 0.34 * fieldView.pitch - zRelativeM * 0.42 * fieldView.zoom,
  };
}

function povRelativeHeading(feed, headingDeg = 0) {
  void feed;
  return headingDeg + (fieldView.yaw * 180) / Math.PI;
}

function drawPovMapBackground(width, height) {
  const bg = povCtx.createLinearGradient(0, 0, 0, height);
  bg.addColorStop(0, "#101923");
  bg.addColorStop(0.58, "#111b1d");
  bg.addColorStop(1, "#090d0f");
  povCtx.fillStyle = bg;
  povCtx.fillRect(0, 0, width, height);

  const glow = povCtx.createRadialGradient(width * 0.5, height * 0.48, 20, width * 0.5, height * 0.48, width * 0.72);
  glow.addColorStop(0, "rgba(85, 214, 166, 0.13)");
  glow.addColorStop(0.5, "rgba(121, 184, 255, 0.06)");
  glow.addColorStop(1, "rgba(9, 13, 15, 0)");
  povCtx.fillStyle = glow;
  povCtx.fillRect(0, 0, width, height);
}

function drawPov3DGrid(feed, width, height) {
  void feed;
  const extent = 720;
  const step = 120;
  const anchor = {
    x: Math.round(FIELD_VIEW_ANCHOR.x / step) * step,
    y: Math.round(FIELD_VIEW_ANCHOR.y / step) * step,
  };

  povCtx.save();
  povCtx.lineWidth = 1;
  for (let offset = -extent; offset <= extent; offset += step) {
    const major = offset % 240 === 0;
    povCtx.strokeStyle = major ? "rgba(245, 241, 232, 0.2)" : "rgba(245, 241, 232, 0.1)";

    povCtx.beginPath();
    for (let u = -extent; u <= extent; u += step / 2) {
      const point = { x: anchor.x + u, y: anchor.y + offset };
      const projected = projectPovMapPoint(
        feed,
        point,
        width,
        height,
        terrainHeightAt(point.x, point.y) - FIELD_VIEW_ANCHOR.z,
      );
      if (u === -extent) povCtx.moveTo(projected.x, projected.y);
      else povCtx.lineTo(projected.x, projected.y);
    }
    povCtx.stroke();

    povCtx.beginPath();
    for (let v = -extent; v <= extent; v += step / 2) {
      const point = { x: anchor.x + offset, y: anchor.y + v };
      const projected = projectPovMapPoint(
        feed,
        point,
        width,
        height,
        terrainHeightAt(point.x, point.y) - FIELD_VIEW_ANCHOR.z,
      );
      if (v === -extent) povCtx.moveTo(projected.x, projected.y);
      else povCtx.lineTo(projected.x, projected.y);
    }
    povCtx.stroke();
  }
  povCtx.restore();
}

function projectPovTerrainPoint(feed, point, width, height) {
  return projectPovMapPoint(
    feed,
    point,
    width,
    height,
    terrainHeightAt(point.x, point.y) - FIELD_VIEW_ANCHOR.z,
  );
}

function drawPovProjectedSegment(feed, a, b, width, height, offsetM = 0) {
  const segment = offsetM ? routeSegmentOffset(a, b, offsetM) : { a, b };
  const start = projectPovTerrainPoint(feed, segment.a, width, height);
  const end = projectPovTerrainPoint(feed, segment.b, width, height);
  povCtx.moveTo(start.x, start.y);
  povCtx.lineTo(end.x, end.y);
}

function drawPovRouteGuardCorridor(feed, width, height) {
  povCtx.save();
  povCtx.lineCap = "round";
  povCtx.lineJoin = "round";

  povCtx.strokeStyle = "rgba(85, 214, 166, 0.12)";
  povCtx.lineWidth = 20;
  povCtx.beginPath();
  for (let index = 0; index < ROUTE_GUARD_PATH.length - 1; index += 1) {
    drawPovProjectedSegment(feed, ROUTE_GUARD_PATH[index], ROUTE_GUARD_PATH[index + 1], width, height);
  }
  povCtx.stroke();

  for (const offset of [-ROUTE_GUARD_HALF_WIDTH_M, ROUTE_GUARD_HALF_WIDTH_M]) {
    povCtx.strokeStyle = "rgba(85, 214, 166, 0.72)";
    povCtx.lineWidth = 2;
    povCtx.beginPath();
    for (let index = 0; index < ROUTE_GUARD_PATH.length - 1; index += 1) {
      drawPovProjectedSegment(
        feed,
        ROUTE_GUARD_PATH[index],
        ROUTE_GUARD_PATH[index + 1],
        width,
        height,
        offset,
      );
    }
    povCtx.stroke();
  }

  povCtx.strokeStyle = "rgba(230, 195, 92, 0.8)";
  povCtx.lineWidth = 2.4;
  povCtx.setLineDash([12, 8]);
  povCtx.beginPath();
  for (let index = 0; index < ROUTE_GUARD_PATH.length - 1; index += 1) {
    drawPovProjectedSegment(feed, ROUTE_GUARD_PATH[index], ROUTE_GUARD_PATH[index + 1], width, height);
  }
  povCtx.stroke();
  povCtx.setLineDash([]);

  const label = projectPovTerrainPoint(feed, ROUTE_GUARD_PATH[2], width, height);
  povCtx.fillStyle = "rgba(8, 13, 15, 0.76)";
  povCtx.fillRect(label.x - 10, label.y - 30, 140, 22);
  povCtx.fillStyle = "#55d6a6";
  povCtx.font = "12px Inter, Arial";
  povCtx.fillText("Route Guard Corridor", label.x - 2, label.y - 14);
  povCtx.restore();
}

function drawPovHazards(feed, width, height) {
  const scale = mapProjectionScale(width, height);
  for (const hazard of hazards) {
    const distance = Math.hypot(hazard.x - FIELD_VIEW_ANCHOR.x, hazard.y - FIELD_VIEW_ANCHOR.y);
    if (distance > 780) continue;
    const projected = projectPovMapPoint(
      feed,
      hazard,
      width,
      height,
      terrainHeightAt(hazard.x, hazard.y) - FIELD_VIEW_ANCHOR.z,
    );
    const critical = hazard.severity === "critical";
    povCtx.save();
    povCtx.fillStyle = critical ? "rgba(255, 93, 93, 0.12)" : "rgba(230, 195, 92, 0.12)";
    povCtx.strokeStyle = critical ? "rgba(255, 93, 93, 0.56)" : "rgba(230, 195, 92, 0.48)";
    povCtx.lineWidth = 2;
    povCtx.beginPath();
    povCtx.ellipse(projected.x, projected.y, hazard.r * scale * 0.82, hazard.r * scale * 0.38, 0, 0, Math.PI * 2);
    povCtx.fill();
    povCtx.stroke();
    povCtx.fillStyle = "#f5f1e8";
    povCtx.font = "12px Inter, Arial";
    povCtx.fillText(hazard.label, projected.x + 10, projected.y - 8);
    povCtx.restore();
  }
}

function drawPovDetectionFrustum(feed, width, height) {
  const origin = projectPovMapPoint(feed, feed, width, height, feed.z - FIELD_VIEW_ANCHOR.z);
  const heading = (feed.heading * Math.PI) / 180;
  const range = 560;
  const left = {
    x: feed.x + Math.cos(heading - 0.55) * range,
    y: feed.y + Math.sin(heading - 0.55) * range,
  };
  const right = {
    x: feed.x + Math.cos(heading + 0.55) * range,
    y: feed.y + Math.sin(heading + 0.55) * range,
  };
  const leftProjected = projectPovMapPoint(
    feed,
    left,
    width,
    height,
    terrainHeightAt(left.x, left.y) - FIELD_VIEW_ANCHOR.z,
  );
  const rightProjected = projectPovMapPoint(
    feed,
    right,
    width,
    height,
    terrainHeightAt(right.x, right.y) - FIELD_VIEW_ANCHOR.z,
  );

  povCtx.save();
  povCtx.fillStyle = "rgba(85, 214, 166, 0.08)";
  povCtx.strokeStyle = "rgba(85, 214, 166, 0.34)";
  povCtx.lineWidth = 1.5;
  povCtx.beginPath();
  povCtx.moveTo(origin.x, origin.y);
  povCtx.lineTo(leftProjected.x, leftProjected.y);
  povCtx.lineTo(rightProjected.x, rightProjected.y);
  povCtx.closePath();
  povCtx.fill();
  povCtx.stroke();
  povCtx.restore();
}

function drawPovObjects(feed, visible, width, height) {
  overlay.innerHTML = "";
  povHitTargets = [];
  const selected = {
    ...feed,
    range: 0,
    bearingDeg: 0,
    altitudeDelta: 0,
    className: "Selected Node",
    detectionConfidence: 1,
    threat: "watch",
    targetId: feed.id,
    trackStatus: "selected",
    trackSources: ["Selected"],
    observationCount: 1,
  };
  const hasSelectedFeedTrack = visible.some((obj) => obj.targetId === feed.id || obj.id === feed.id);
  const mapObjects = hasSelectedFeedTrack ? visible : [selected, ...visible];
  const sorted = mapObjects
    .map((obj) => ({
      ...obj,
      ground: projectPovMapPoint(
        feed,
        obj,
        width,
        height,
        terrainHeightAt(obj.x, obj.y) - FIELD_VIEW_ANCHOR.z,
      ),
      air: projectPovMapPoint(feed, obj, width, height, obj.z - FIELD_VIEW_ANCHOR.z),
    }))
    .sort((a, b) => a.ground.y - b.ground.y);
  overlay.dataset.identityReport = sorted
    .filter((obj) => obj.id !== feed.id && isKnownFriendly(obj))
    .map((obj) => `${obj.callsign}:${obj.className}:${obj.threat}`)
    .join("|");
  overlay.dataset.fusionIds = visible
    .map((obj) => obj.targetId || obj.id)
    .sort()
    .join("|");
  overlay.dataset.selectedPlatform = feed.id;
  overlay.dataset.selectedContact = selectedContactId || "";
  overlay.dataset.fieldViewAnchor = `${FIELD_VIEW_ANCHOR.x},${FIELD_VIEW_ANCHOR.y},${FIELD_VIEW_ANCHOR.z}`;
  const labeledIds = new Set(priorityLabeledObjects(sorted, feed.id).map((obj) => obj.id));
  const placedLabelRects = [];

  for (const obj of sorted) {
    drawPovObjectMarker(feed, obj);
    povHitTargets.push({
      id: obj.id,
      targetId: obj.targetId || obj.id,
      obj,
      x: obj.air.x,
      y: obj.air.y,
      radius: obj.type === "vehicle" ? 32 : 26,
    });
    if (labeledIds.has(obj.id)) {
      addDetectionLabel(obj, width, height, placedLabelRects);
    }
  }
}

function priorityLabeledObjects(objects, feedId) {
  const ranked = objects
    .filter((obj) => obj.id !== feedId && obj.targetId !== feedId)
    .sort((a, b) => {
      const threatDelta = (b.threat === "critical") - (a.threat === "critical");
      if (threatDelta) return threatDelta;
      const friendlyDelta = (a.affiliation === "friendly" ? 1 : 0) - (b.affiliation === "friendly" ? 1 : 0);
      if (friendlyDelta) return friendlyDelta;
      const rangeDelta = a.range - b.range;
      if (Math.abs(rangeDelta) > 1) return rangeDelta;
      return b.detectionConfidence - a.detectionConfidence;
    });
  const selected = selectedContactId
    ? ranked.find((obj) => obj.id === selectedContactId || obj.targetId === selectedContactId)
    : null;
  if (!selected) return ranked.slice(0, MAX_VISIBLE_DETECTION_LABELS);
  return [
    selected,
    ...ranked.filter((obj) => obj.id !== selected.id).slice(0, MAX_VISIBLE_DETECTION_LABELS - 1),
  ];
}

function drawPovObjectMarker(feed, obj) {
  const selectedPlatform = obj.id === selectedId || obj.targetId === selectedId;
  const selectedContact = obj.id === selectedContactId || obj.targetId === selectedContactId;
  const color = selectedPlatform ? "#f5f1e8" : colors[obj.key] || "#55d6a6";
  const markerRadius = obj.type === "ground" ? 8 : 11;
  const critical = obj.threat === "critical";

  povCtx.save();
  povCtx.strokeStyle = selectedContact ? "#e6c35c" : critical ? "#ff5d5d" : "rgba(245, 241, 232, 0.78)";
  povCtx.fillStyle = "rgba(0, 0, 0, 0.28)";
  povCtx.lineWidth = 1.5;
  povCtx.beginPath();
  povCtx.ellipse(obj.ground.x, obj.ground.y, markerRadius * 1.7, markerRadius * 0.6, 0, 0, Math.PI * 2);
  povCtx.fill();

  povCtx.strokeStyle = "rgba(245, 241, 232, 0.28)";
  povCtx.beginPath();
  povCtx.moveTo(obj.ground.x, obj.ground.y);
  povCtx.lineTo(obj.air.x, obj.air.y);
  povCtx.stroke();

  povCtx.fillStyle = color;
  povCtx.strokeStyle = selectedContact ? "#e6c35c" : critical ? "#ff5d5d" : "#f5f1e8";
  povCtx.lineWidth = selectedContact || critical ? 3 : 2;
  if (obj.type === "vehicle") {
    drawWheeledVehicleGlyph(povCtx, obj.air.x, obj.air.y, povRelativeHeading(feed, obj.heading || 0), 0.88);
  } else if (["fixed-wing", "quadrotor", "ground"].includes(obj.type)) {
    drawPlatformGlyph(
      povCtx,
      obj.air.x,
      obj.air.y,
      { ...obj, heading: povRelativeHeading(feed, obj.heading || 0) },
      color,
      obj.id === selectedId,
    );
  } else {
    povCtx.beginPath();
    if (obj.type === "unknown-contact") {
      povCtx.moveTo(obj.air.x, obj.air.y - markerRadius);
      povCtx.lineTo(obj.air.x + markerRadius, obj.air.y);
      povCtx.lineTo(obj.air.x, obj.air.y + markerRadius);
      povCtx.lineTo(obj.air.x - markerRadius, obj.air.y);
      povCtx.closePath();
    } else if (obj.type === "unknown-uas") {
      povCtx.moveTo(obj.air.x, obj.air.y - markerRadius * 0.95);
      povCtx.lineTo(obj.air.x + markerRadius * 1.1, obj.air.y + markerRadius * 0.75);
      povCtx.lineTo(obj.air.x - markerRadius * 1.1, obj.air.y + markerRadius * 0.75);
      povCtx.closePath();
    } else if (obj.type === "ground") {
      povCtx.rect(obj.air.x - markerRadius, obj.air.y - markerRadius / 2, markerRadius * 2, markerRadius);
    } else if (obj.type === "personnel") {
      povCtx.arc(obj.air.x - 5, obj.air.y, 4.5, 0, Math.PI * 2);
      povCtx.moveTo(obj.air.x + 9, obj.air.y);
      povCtx.arc(obj.air.x + 5, obj.air.y, 4.5, 0, Math.PI * 2);
    } else if (obj.type === "rf-source") {
      povCtx.moveTo(obj.air.x, obj.air.y - markerRadius);
      povCtx.lineTo(obj.air.x + markerRadius, obj.air.y);
      povCtx.lineTo(obj.air.x, obj.air.y + markerRadius);
      povCtx.lineTo(obj.air.x - markerRadius, obj.air.y);
      povCtx.closePath();
    } else if (obj.type === "fixed-wing") {
      povCtx.moveTo(obj.air.x, obj.air.y - markerRadius);
      povCtx.lineTo(obj.air.x + markerRadius * 1.8, obj.air.y + markerRadius * 0.8);
      povCtx.lineTo(obj.air.x, obj.air.y + markerRadius * 0.25);
      povCtx.lineTo(obj.air.x - markerRadius * 1.8, obj.air.y + markerRadius * 0.8);
      povCtx.closePath();
    } else if (obj.type === "small-uas") {
      povCtx.moveTo(obj.air.x, obj.air.y - markerRadius * 0.85);
      povCtx.lineTo(obj.air.x + markerRadius, obj.air.y + markerRadius * 0.65);
      povCtx.lineTo(obj.air.x - markerRadius, obj.air.y + markerRadius * 0.65);
      povCtx.closePath();
    } else {
      povCtx.arc(obj.air.x, obj.air.y, markerRadius, 0, Math.PI * 2);
    }
    povCtx.fill();
    povCtx.stroke();
  }

  if (!selectedPlatform) {
    const boxW = obj.type === "ground" ? 42 : 54;
    const boxH = obj.type === "ground" ? 24 : 34;
    povCtx.strokeStyle = selectedContact
      ? "rgba(230, 195, 92, 0.95)"
      : critical
        ? "rgba(255, 93, 93, 0.9)"
        : "rgba(85, 214, 166, 0.86)";
    povCtx.setLineDash([7, 5]);
    povCtx.strokeRect(obj.air.x - boxW / 2, obj.air.y - boxH / 2, boxW, boxH);
    povCtx.setLineDash([]);
  }
  povCtx.restore();
}

function rectsOverlap(a, b) {
  return !(
    a.x + a.w < b.x
    || b.x + b.w < a.x
    || a.y + a.h < b.y
    || b.y + b.h < a.y
  );
}

function placeDetectionLabel(obj, width, height, placedRects) {
  const labelW = 228;
  const labelH = 88;
  const minLabelY = Math.min(height - labelH - 10, Math.max(160, height * 0.38));
  const maxLabelY = height - labelH - 10;
  const maxLabelX = width - labelW - 10;
  const candidates = [
    { x: obj.air.x + 16, y: obj.air.y - 14 },
    { x: obj.air.x + 16, y: obj.air.y + 18 },
    { x: obj.air.x - labelW - 16, y: obj.air.y - 14 },
    { x: obj.air.x - labelW - 16, y: obj.air.y + 18 },
    { x: obj.air.x - labelW / 2, y: obj.air.y - labelH - 18 },
  ].map((candidate) => ({
    x: clamp(candidate.x, 10, maxLabelX),
    y: clamp(candidate.y, minLabelY, maxLabelY),
    w: labelW,
    h: labelH,
  }));

  let rect = candidates.find(
    (candidate) => placedRects.every((placed) => !rectsOverlap(candidate, placed)),
  );
  if (!rect) {
    const nudge = labelH + 8;
    const shiftedCandidates = [];
    for (const candidate of candidates) {
      for (let step = 1; step <= 5; step += 1) {
        for (const direction of [1, -1]) {
          shiftedCandidates.push({
            ...candidate,
            y: clamp(candidate.y + direction * step * nudge, minLabelY, maxLabelY),
          });
        }
      }
    }
    rect = shiftedCandidates.find(
      (candidate) => placedRects.every((placed) => !rectsOverlap(candidate, placed)),
    );
  }
  if (!rect) {
    const railCandidates = [];
    const xSlots = [
      clamp(obj.air.x - labelW / 2, 10, maxLabelX),
      clamp(obj.air.x + 84, 10, maxLabelX),
      clamp(obj.air.x - labelW - 84, 10, maxLabelX),
      10,
      maxLabelX,
    ];
    for (const x of [...new Set(xSlots.map((value) => Math.round(value)))]) {
      for (let y = minLabelY; y <= maxLabelY; y += labelH + 8) {
        railCandidates.push({ x, y, w: labelW, h: labelH });
      }
    }
    railCandidates.sort((a, b) => {
      const distanceA = Math.hypot(a.x + labelW / 2 - obj.air.x, a.y + labelH / 2 - obj.air.y);
      const distanceB = Math.hypot(b.x + labelW / 2 - obj.air.x, b.y + labelH / 2 - obj.air.y);
      return distanceA - distanceB;
    });
    rect = railCandidates.find(
      (candidate) => placedRects.every((placed) => !rectsOverlap(candidate, placed)),
    );
  }
  if (!rect) rect = candidates[0];
  placedRects.push(rect);
  return rect;
}

function compactTrackSource(source) {
  const cleaned = String(source || "")
    .replace(/^uav-/i, "")
    .replace(/[^a-z0-9]/gi, "");
  return cleaned ? cleaned[0].toUpperCase() : "";
}

function formatTrackSourcePair(sources = []) {
  const compact = sources.slice(0, 2).map(compactTrackSource).filter(Boolean);
  return compact.length ? compact.join("+") : "";
}

function addDetectionLabel(obj, width, height, placedRects) {
  const rect = placeDetectionLabel(obj, width, height, placedRects);
  const label = document.createElement("div");
  const selectedClass = obj.id === selectedContactId || obj.targetId === selectedContactId
    ? "selected-contact"
    : "";
  label.className = `target-label ${obj.threat} ${obj.trackStatus || ""} ${obj.type || ""} ${selectedClass}`;
  label.dataset.trackId = obj.id;
  label.title = `Select ${obj.className}`;
  label.style.left = `${rect.x}px`;
  label.style.top = `${rect.y}px`;

  const header = document.createElement("div");
  header.className = "target-label-header";
  const title = document.createElement("strong");
  title.textContent = obj.className;
  const confidence = document.createElement("span");
  confidence.className = "target-confidence";
  confidence.textContent = `${Math.round(obj.detectionConfidence * 100)}%`;
  header.append(title, confidence);

  const grid = document.createElement("div");
  grid.className = "target-label-grid";
  const sourceCopy = formatTrackSourcePair(obj.trackSources);
  const statusCopy = obj.affiliation === "friendly"
    ? "Shared Friendly ID"
    : obj.classifierCue
      ? `${displayClassifierCueLabel(obj.classifierCue.label)} ${classifierCueConfidencePct(obj.classifierCue)}%`
    : obj.trainingClass
      ? `${displayClassifierCueLabel(obj.trainingClass)} Frame`
    : obj.trackStatus === "memory"
      ? `Last Seen ${Math.round(obj.trackAge)}s`
      : "Live Track";
  for (const value of [
    obj.callsign,
    formatMeters(obj.range),
    statusCopy,
    sourceCopy ? `Src ${sourceCopy}` : "Local Cue",
  ]) {
    const chip = document.createElement("span");
    chip.className = "target-chip";
    chip.textContent = value;
    grid.appendChild(chip);
  }
  label.append(header, grid);
  label.addEventListener("click", (event) => {
    event.stopPropagation();
    selectFusedObject(obj);
  });
  overlay.appendChild(label);
}

function selectFusedObject(obj) {
  const targetId = obj.targetId || obj.id;
  const friendly = feeds.find((feed) => feed.id === targetId);
  if (friendly) {
    selectPlatform(friendly.id, {
      selectedContactId: obj.id,
      log: `Selected ${friendly.callsign} In Shared Field View.`,
    });
  } else {
    selectedContactId = obj.id;
    pushLog(`Selected ${obj.className}: ${obj.callsign} From Fused Track Memory.`);
    renderFrame();
  }
}

function canvasPointFromEvent(event) {
  const rect = povCanvas.getBoundingClientRect();
  return {
    x: ((event.clientX - rect.left) / rect.width) * povCanvas.width,
    y: ((event.clientY - rect.top) / rect.height) * povCanvas.height,
  };
}

function findPovHit(point) {
  for (const hit of [...povHitTargets].reverse()) {
    const distance = Math.hypot(point.x - hit.x, point.y - hit.y);
    if (distance <= hit.radius) return hit.obj;
  }
  return null;
}

function handlePovPointerDown(event) {
  fieldView.dragging = true;
  fieldView.moved = false;
  fieldView.startX = event.clientX;
  fieldView.startY = event.clientY;
  fieldView.lastX = event.clientX;
  fieldView.lastY = event.clientY;
  povCanvas.setPointerCapture?.(event.pointerId);
}

function handlePovPointerMove(event) {
  if (!fieldView.dragging) return;
  const dx = event.clientX - fieldView.lastX;
  const dy = event.clientY - fieldView.lastY;
  const total = Math.hypot(event.clientX - fieldView.startX, event.clientY - fieldView.startY);
  if (total > 4) fieldView.moved = true;
  fieldView.yaw = wrapAngle(fieldView.yaw + dx * 0.007);
  fieldView.pitch = clamp(fieldView.pitch + dy * 0.0025, 0.58, 1.08);
  fieldView.lastX = event.clientX;
  fieldView.lastY = event.clientY;
  renderFrame();
}

function handlePovPointerUp(event) {
  if (!fieldView.dragging) return;
  fieldView.dragging = false;
  povCanvas.releasePointerCapture?.(event.pointerId);
  if (fieldView.moved) return;
  const hit = findPovHit(canvasPointFromEvent(event));
  if (hit) selectFusedObject(hit);
}

function handlePovWheel(event) {
  event.preventDefault();
  const zoomDelta = event.deltaY > 0 ? -0.08 : 0.08;
  fieldView.zoom = clamp(fieldView.zoom + zoomDelta, 0.78, 1.42);
  renderFrame();
}

function drawPovTelemetry(feed, visible, width, height) {
  povCtx.fillStyle = "rgba(10, 15, 18, 0.62)";
  povCtx.fillRect(18, 18, 260, 78);
  povCtx.fillStyle = "#f2efe5";
  povCtx.font = "14px Inter, Arial";
  povCtx.fillText("Fused 3D Field View", 32, 42);
  povCtx.fillText(`SELECTED ${feed.callsign}  HDG ${Math.round((feed.heading + 360) % 360)}`, 32, 66);
  povCtx.fillText(`FUSED ${visible.length}  BAT ${Math.round(feed.battery)}%`, 32, 90);
}

function drawPovQuantificationPanel(visible, width, height) {
  const avgConfidence = visible.length
    ? visible.reduce((sum, obj) => sum + obj.detectionConfidence, 0) / visible.length
    : 0;
  const airTracks = visible.filter((obj) => obj.type !== "ground").length;
  const vehicleFrames = visible.filter((obj) => obj.type === "vehicle").length;
  const cue = classifierCueClassification();
  const classifierLine = cue
    ? `H100 ${displayClassifierCueLabel(cue.class_label)} · ${classifierCueConfidencePct(cue)}%`
    : `${vehicleFrames} Vehicle Frames For Classifier`;
  const panelWidth = 228;
  const x = width - panelWidth - 18;
  const y = 18;
  povCtx.save();
  povCtx.fillStyle = "rgba(8, 13, 15, 0.68)";
  povCtx.strokeStyle = "rgba(85, 214, 166, 0.36)";
  povCtx.lineWidth = 1;
  povCtx.beginPath();
  povCtx.roundRect(x, y, panelWidth, 98, 8);
  povCtx.fill();
  povCtx.stroke();

  povCtx.fillStyle = "#55d6a6";
  povCtx.font = "12px Inter, Arial";
  povCtx.fillText("Local Cue Pass", x + 14, y + 24);
  povCtx.fillStyle = "#f5f1e8";
  povCtx.font = "20px Inter, Arial";
  povCtx.fillText(`${visible.length} Quantified`, x + 14, y + 50);
  povCtx.fillStyle = "rgba(245, 241, 232, 0.72)";
  povCtx.font = "12px Inter, Arial";
  povCtx.fillText(
    `${airTracks} Air Tracks · ${Math.round(avgConfidence * 100)}% Avg Confidence`,
    x + 14,
    y + 70,
  );
  povCtx.fillText(classifierLine, x + 14, y + 88);
  povCtx.restore();
}

function renderFeeds() {
  document.querySelector("#asset-list").innerHTML = feeds
    .map((feed) => {
      const hit = bvhQuery(feed).find((item) => item.severity === "critical" && item.distance < item.radius);
      const dotClass = hit ? "critical" : feed.battery < 70 ? "warn" : "";
      const selected = feed.id === selectedId ? "selected" : "";
      const latClass = latencyClass(feed.latency);
      const latency = formatLatencyMs(feed.latency);
      const npuCopy = feed.npu
        ? `<div class="asset-meta npu-meta">Onboard ${feed.npu.device} · ${feed.npu.cue} · ${Math.round(feed.npu.confidence * 100)}%</div>`
        : "";
      return `<button class="asset-row ${selected}" data-feed="${feed.id}">
        <div>
          <strong>${feed.callsign}</strong>
          <div class="asset-meta">${displayCommand(feed.command)} · ${formatMeters(feed.z)} · ${Math.round(feed.battery)}% · <span class="feed-latency compact ${latClass}">${latency}</span></div>
          ${npuCopy}
        </div>
        <span class="asset-dot ${dotClass}"></span>
      </button>`;
    })
    .join("");
  document.querySelectorAll(".asset-row").forEach((row) => {
    row.addEventListener("click", () => {
      selectPlatform(row.dataset.feed);
    });
  });
}

function renderFeedTabs() {
  const el = document.querySelector("#feed-tabs");
  if (!el) return;
  const signature = feeds.map((feed) => feed.id).join("|");

  if (el.dataset.signature !== signature) {
    el.dataset.signature = signature;
    el.innerHTML = feeds.map((feed) => {
      return `<button type="button" class="feed-tab" data-feed="${feed.id}" aria-pressed="false" aria-current="false" title="Select ${feed.callsign}">
        ${feed.callsign}<span class="feed-tab-confidence"></span>
      </button>`;
    }).join("");

    el.querySelectorAll(".feed-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        selectPlatform(tab.dataset.feed);
      });
    });
  }

  for (const feed of feeds) {
    const tab = el.querySelector(`.feed-tab[data-feed="${feed.id}"]`);
    if (!tab) continue;
    const active = feed.id === selectedId;
    const confidence = Math.round((feed.npu?.confidence || feed.confidence) * 100);
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-pressed", String(active));
    tab.setAttribute("aria-current", active ? "true" : "false");
    const confidenceEl = tab.querySelector(".feed-tab-confidence");
    if (confidenceEl) confidenceEl.textContent = `${confidence}%`;
  }
}

function selectPlatform(feedId, options = {}) {
  const feed = feeds.find((item) => item.id === feedId);
  if (!feed) return;
  selectedId = feed.id;
  selectedContactId = options.selectedContactId || null;
  pushLog(options.log || `${feed.callsign} Selected In Shared Field View.`);
  renderFrame();
}

function renderFeedQuality() {
  const all = allFeeds();
  const avgFresh = all.reduce((s, f) => s + f.freshness, 0) / all.length;
  const freshnessLabel = avgFresh > 0.85 ? "Fresh" : avgFresh > 0.6 ? "Degraded" : "Stale";
  document.querySelector("#feed-count").textContent = `${feeds.length} Feeds`;
  document.querySelector("#feed-freshness").textContent = freshnessLabel;
  document.querySelector("#spool-depth").textContent = `Spool ${spoolDepth}`;

  document.querySelector("#feed-quality").innerHTML = allFeeds()
    .map((feed) => {
      const freshPct = Math.round(feed.freshness * 100);
      const confPct = Math.round(feed.confidence * 100);
      const npuPct = Math.round((feed.npu?.confidence || feed.confidence) * 100);
      const latClass = latencyClass(feed.latency);
      const latency = formatLatencyMs(feed.latency);
      return `<div class="feed-row">
        <div class="feed-header"><strong>${feed.callsign}</strong><span class="feed-latency ${latClass}">${latency}</span></div>
        <div class="feed-metrics">
          <div class="metric-bar"><span class="metric-label">Fresh</span><div class="bar-track"><span class="bar-fill" style="width:${freshPct}%"></span></div></div>
          <div class="metric-bar"><span class="metric-label">Conf</span><div class="bar-track"><span class="bar-fill" style="width:${confPct}%"></span></div></div>
          <div class="metric-bar"><span class="metric-label">NPU</span><div class="bar-track"><span class="bar-fill" style="width:${npuPct}%"></span></div></div>
        </div>
      </div>`;
    })
    .join("");
}

function renderStagedPacket() {
  const packetEl = document.querySelector("#staged-packet");
  if (stagedCommands.length === 0) {
    packetEl.innerHTML = '<div class="packet-empty subtle">No Staged Commands — Local C2 Issues Commands Directly</div>';
    return;
  }
  packetEl.innerHTML = stagedCommands
    .slice(0, 5)
    .map((cmd) => {
      return `<div class="packet-item"><span class="packet-id">${cmd.id}</span><span class="packet-cmd">${cmd.callsign} ${displayCommand(cmd.command)}</span><span class="packet-ts">T+${cmd.ts.toFixed(1)}s</span></div>`;
    })
    .join("");
}

function renderHardware(feed, hits) {
  const status = modeCopy();
  void status;
  const rtDecision = feed.rtControl || planRtGeometryControl(feed, hits);
  const bvhMs = (rayPath === "cuda" ? 2.4 : 8.8) + hits.length * (rayPath === "cuda" ? 0.22 : 0.7);
  const unknowns = sceneClassTargets.filter((item) => item.type.startsWith("unknown"));
  const npuReady = feeds.filter((item) => item.npu).length;
  const liveTracks = [...fusedTracks.values()].filter((track) => simTime - track.lastSeen <= TRACK_MEMORY_SECONDS).length;
  const criticalHit = hits.find((hit) => hit.severity === "critical" && hit.distance < hit.radius);
  const nearestHit = hits[0];
  const routeState = criticalHit ? "Blocked" : nearestHit ? "Monitoring" : "Guarded";
  const rows = [
    ["Fusion Authority", "Laptop-Local Sensor Fusion", "Good"],
    ["Local AOI", "Synthesized 1.2 km Field View", "Good"],
    ["Terrain Mesh", `${terrainTriangleCount()} Triangles`, "Good"],
    ["Edge Compute", `${edgeComputeSummaryLabel()} · ${edgeComputeFreshnessLabel()}`, rayPath === "cuda" || edgeCompute?.npu?.ready ? "Good" : "Watch"],
    ["RT Control", `${feed.callsign} ${displayCommand(rtDecision.command)} · ${rtDecision.shortLabel} · ${rtDecision.backend}`, rtDecision.priority === "Critical" ? "Watch" : "Good"],
    ["Corridor Geometry", `${routeState} · ${formatMeters(routeLengthMeters())} · ${geometryBackendLabel()}`, criticalHit ? "Watch" : "Good"],
    ["Spatial Geometry", `${hits.length} Checks · ${formatLatencyMs(bvhMs)} · ${geometryBackendLabel()}`, "Good"],
    ["Track Memory", `${liveTracks} Fused Tracks · ${TRACK_MEMORY_SECONDS}s Hold`, "Good"],
    ["H100 Classifier", `${edgeClassifierLabel()} · ${classifierCueDetail()}`, classifierCueClassification() ? "Good" : "Watch"],
    ["Distributed NPU CV", `${npuReady}/${feeds.length} Air Nodes · ${unknowns.length} Unknowns · ${edgeNpuLabel()}`, "Good"],
    [
      "Demo Incident",
      localC2Incident.active
        ? `T+${localC2Incident.triggeredAt.toFixed(0)}s Local C2 Took Authority`
        : `Armed T+${DEMO_INCIDENT_TRIGGER_S}s`,
      localC2Incident.active ? "Watch" : "Good",
    ],
    ["Spool Buffer", `${spoolDepth} Staged For Gate`, spoolDepth > 0 ? "Watch" : "Good"],
    ["Sync Watermark", `T+${syncWatermark.toFixed(1)}s`, spoolDepth > 0 ? "Watch" : "Good"],
  ];
  document.querySelector("#hardware-list").innerHTML = rows
    .map(
      ([name, detail, kind]) =>
        `<div class="status-row"><div><strong>${name}</strong><div class="status-detail">${detail}</div></div><span class="status-chip ${kind.toLowerCase()}">${kind}</span></div>`,
    )
    .join("");
  setText("#bvh-label", rtDecision.shortLabel);
  setText("#compute-label", rayPath === "cuda" ? "Accelerated RT Control" : edgeComputeSummaryLabel());
  setText("#fusion-badge", `Route Guard ${routeState}`);
  setText(
    "#map-hud-copy",
    "Route Guard · Cut Off From Command · Laptop C2 Holds Corridor",
  );
  setText("#range-label", nearestHit ? `${formatMeters(nearestHit.distance)}` : "Clear");
  setText("#pov-title", "Route Guard 3D Field View");
}

function renderVision(scores) {
  document.querySelector("#vision-scores").innerHTML = scores
    .map(
      ([label, score]) =>
        `<div class="score-row"><strong>${label}</strong><span>${Math.round(score * 100)}%</span><div class="score-bar"><span style="width:${score * 100}%"></span></div></div>`,
    )
    .join("");
}

function renderAlerts(feed, hits, scores) {
  const alerts = [];
  const critical = hits.find((hit) => hit.severity === "critical" && hit.distance < hit.radius);
  const visibleUnknown = visibleObjects(feed).find((obj) => obj.type.startsWith("unknown") && obj.threat === "critical");
  if (localC2Incident.active) {
    alerts.push(["critical", "Incident: Unknown Contact In Corridor; Local C2 Takeover Active"]);
  }
  if (critical) {
    alerts.push(["critical", `${feed.callsign} Inside ${critical.label}; Route Correction Active`]);
  } else if (visibleUnknown) {
    alerts.push(["critical", `${visibleUnknown.callsign} In Route Corridor; Identify Before Passage`]);
  } else if (scores[0][0] === "Restricted Volume In POV") {
    alerts.push(["critical", "Restricted Volume In View"]);
  }
  if (spoolDepth > 0) {
    alerts.push(["watch", `${spoolDepth} Commands Queued For Operator Sync Gate`]);
  }
  if (feed.battery < 70) alerts.push(["watch", `${feed.callsign} Battery Near Return Threshold`]);
  if (alerts.length === 0) alerts.push(["watch", "Fusion Node Nominal"]);
  document.querySelector("#alert-list").innerHTML = alerts
    .map(([level, text]) => `<div class="alert-row ${level}">${text}</div>`)
    .join("");
}

function updateModeChrome() {
  const status = modeCopy();
  const pill = document.querySelector("#mode-status");
  pill.textContent = CONNECTIVITY_LABELS[connectivityMode];
  pill.className = `mode-pill ${CONNECTIVITY_CLASSES[connectivityMode]}`;
  setText("#sync-count", String(status.sync));
  setText("#sync-watermark", `Watermark T+${status.watermark.toFixed(1)}s`);
  setText("#clock-label", `T+${simTime.toFixed(1)}s`);
  const syncPill = document.querySelector("#sync-state-pill");
  if (syncPill) {
    syncPill.textContent = spoolDepth > 0 ? `${spoolDepth} Staged` : "Sync Idle";
    syncPill.classList.toggle("staged", spoolDepth > 0);
  }
  // Sync gate: disable release button unless in ONLINE mode
  const syncBtn = document.querySelector("#sync-now");
  if (syncBtn) {
    syncBtn.disabled = connectivityMode !== "online";
    syncBtn.title = connectivityMode === "online"
      ? "Release Staged Commands To Enterprise"
      : `${CONNECTIVITY_LABELS[connectivityMode]}: Enterprise Sync Blocked`;
  }
  // Update operator-gated copy based on mode
  const syncStatus = document.querySelector("#sync-status");
  if (syncStatus) {
    if (connectivityMode === "offline") {
      syncStatus.textContent = "Offline: Sync Gate Closed · Enterprise Unreachable";
    } else if (connectivityMode === "degraded") {
      syncStatus.textContent = "Degraded: Sync Gate Closed · Commands Queued For Reconnect";
    } else {
      syncStatus.textContent = "Online: Sync Gate Open · Press Release To Sync";
    }
  }
  // Update mode buttons active state
  document.querySelectorAll(".conn-btn").forEach((btn) => {
    const isActive = btn.dataset.mode === connectivityMode;
    btn.classList.toggle("active", isActive);
  });
}

function renderMissionLog() {
  document.querySelector("#mission-log").innerHTML = missionLog
    .map((entry) => `<div class="log-row">${entry}</div>`)
    .join("");
}

function renderSwarmC2() {
  const el = document.querySelector("#swarm-c2");
  if (!el) return;
  el.innerHTML = feeds.map((feed) => {
    const last = swarmTasking.lastCommand[feed.id];
    const latClass = latencyClass(feed.latency);
    const latency = formatLatencyMs(feed.latency);
    const lastCmd = last ? `${displayCommand(last.command)} @ T+${last.ts.toFixed(0)}s` : "—";
    const rtDecision = feed.rtControl || planRtGeometryControl(feed, bvhQuery(feed));
    const commands = ["patrol", "hold", "return", "resume"].map((cmd) => {
      const active = feed.command === cmd ? " active" : "";
      return `<button class="c2-mini${active}" data-drone="${feed.id}" data-cmd="${cmd}" title="Task ${feed.callsign} to ${cmd}">${cmd.slice(0, 2).toUpperCase()}</button>`;
    }).join("");
    return `<div class="c2-drone-row">
      <div class="c2-drone-header">
        <strong>${feed.callsign}</strong>
        <span class="feed-latency compact ${latClass}">${latency}</span>
        <span class="c2-drone-cmd">${displayCommand(feed.command)} · ${Math.round(feed.battery)}% · ${formatMeters(feed.z)}</span>
      </div>
      <div class="c2-drone-meta">Last: ${lastCmd} · RT: ${displayCommand(rtDecision.command)} ${rtDecision.shortLabel}</div>
      <div class="c2-mini-stack">${commands}</div>
    </div>`;
  }).join("");
  el.querySelectorAll(".c2-mini").forEach((btn) => {
    btn.addEventListener("click", () => {
      issueCommandToDrone(btn.dataset.drone, btn.dataset.cmd);
      renderFrame();
    });
  });
}

function renderDeniedProof() {
  const el = document.querySelector("#denied-proof");
  if (!el) return;

  const offlineCapabilities = [
    { name: "Local C2 Authority", status: "active", detail: "Direct command issue to all drones" },
    {
      name: "Incident Takeover",
      status: localC2Incident.active ? "active" : "degraded",
      detail: localC2Incident.active
        ? `${localC2Incident.takeoverCommands} local retasks staged at T+${localC2Incident.triggeredAt.toFixed(0)}s`
        : `Armed for T+${DEMO_INCIDENT_TRIGGER_S}s route incident`,
    },
    { name: "Sensor Fusion", status: "active", detail: "Feeds fused on laptop — no external server" },
    { name: "Automatic Corridor Guard", status: "active", detail: `${rtControlBackendLabel()} Controls Drone Standoff And Hold Decisions` },
    { name: "Distributed NPU CV", status: "active", detail: `${feeds.length} drone NPUs classify simple local cues` },
    { name: "H100 Classifier Cue", status: classifierCueClassification() ? "active" : "degraded", detail: classifierCueDetail() },
    { name: "Alerting Engine", status: "active", detail: "Critical/watch alerts generated offline" },
    { name: "Command Spool Buffer", status: "active", detail: `${spoolDepth} commands held for deferred sync` },
    { name: "Drone Tasking State", status: "active", detail: `${feeds.length} drones tracked, ${swarmTasking.retaskCount} retasks` },
    { name: "Power Posture Manager", status: "active", detail: `${powerSource} — ${Math.round(laptopBattery)}% battery` },
    { name: "Local AOI Cache", status: connectivityMode !== "online" ? "degraded" : "active", detail: connectivityMode === "online" ? "Up to date" : "Cached — no fresh download" },
  ];
  const onlineOnlyCapabilities = [
    { name: "Enterprise Sync", status: connectivityMode === "online" ? "available" : "blocked", detail: connectivityMode === "online" ? "Gate open — release to upload" : `Blocked by ${connectivityMode} mode` },
    { name: "Foundry / Maven Export", status: "blocked", detail: "No connectivity — packets staged locally" },
  ];

  const rows = [...offlineCapabilities, ...onlineOnlyCapabilities].map((cap) => {
    let chipClass = "chip-active";
    let chipLabel = "ACTIVE";
    if (cap.status === "blocked") { chipClass = "chip-Blocked"; chipLabel = "BLOCKED"; }
    else if (cap.status === "degraded") { chipClass = "chip-Degraded"; chipLabel = "DEGRADED"; }
    else if (cap.status === "available") { chipClass = "chip-Available"; chipLabel = "AVAILABLE"; }
    return `<div class="denied-row ${cap.status}">
      <div class="denied-name"><span class="denied-chip ${chipClass}">${chipLabel}</span> ${cap.name}</div>
      <div class="denied-detail">${cap.detail}</div>
    </div>`;
  }).join("");

  const activeCount = offlineCapabilities.filter((c) => c.status === "active").length;
  const totalOffline = offlineCapabilities.length;

  el.innerHTML = `
    <div class="denied-summary">
      <span class="denied-pill denied-pill-ok">${activeCount}/${totalOffline} Capabilities Active Offline</span>
      <span class="denied-pill denied-pill-info">${swarmTasking.history.length} Commands Issued This Session</span>
      <span class="denied-pill denied-pill-warn">${connectivityMode === "offline" ? "FULL DENIED — No Enterprise Dependency" : connectivityMode === "degraded" ? "PARTIAL DENIED — Sync Queued" : "ONLINE — Proof Holds Locally"}</span>
    </div>
    ${rows}
  `;
}

function renderSwarmC2Status() {
  // Update the topbar feed summary with swarm C2 metrics
  const feedCountEl = document.querySelector("#feed-count");
  const retaskEl = document.querySelector("#spool-depth");

  if (feedCountEl) {
    feedCountEl.textContent = `${feeds.length + sceneClassTargets.length + 1} Contacts`;
  }

  // Show retask count in the spool depth pill when there's activity
  if (retaskEl) {
    if (swarmTasking.retaskCount > 0) {
      retaskEl.textContent = `${swarmTasking.retaskCount} Retasks`;
      retaskEl.classList.add("staged");
    } else {
      retaskEl.textContent = `Spool ${spoolDepth}`;
      retaskEl.classList.remove("staged");
    }
  }

  // Update feed freshness based on swarm activity
  const freshnessEl = document.querySelector("#feed-freshness");
  if (freshnessEl) {
    const lastCommandTime = swarmTasking.history.length > 0 ? swarmTasking.history[0].ts : 0;
    const timeSinceCommand = simTime - lastCommandTime;
    if (swarmTasking.history.length === 0) {
      freshnessEl.textContent = "Fresh";
      freshnessEl.classList.remove("staged");
    } else if (timeSinceCommand < 5) {
      freshnessEl.textContent = "Active C2";
      freshnessEl.classList.remove("staged");
    } else {
      freshnessEl.textContent = "Monitoring";
      freshnessEl.classList.remove("staged");
    }
  }
}

function renderFrame() {
  const feed = selectedFeed();
  const visible = visibleObjects(feed);
  const hits = bvhQuery(feed);
  const scores = classifyFrame(feed, visible);
  drawSwarmMap();
  drawPov(feed, visible);
  renderFeeds();
  renderFeedTabs();
  renderFeedQuality();
  renderStagedPacket();
  renderHardware(feed, hits);
  renderVision(scores);
  renderAlerts(feed, hits, scores);
  renderSwarmC2();
  renderDeniedProof();
  renderMissionLog();
  updateModeChrome();
  currentPosture = computePosture();
  document.querySelector("#frame-counter").textContent = simPaused
    ? "Paused"
    : "Field C2 View · Internet Lost · Command Reachback Lost";
  setText(
    "#power-posture-label",
    `${displayTier(currentPosture.tier)} · ${Math.round(laptopBattery)}%`,
  );
  setText("#sync-gate-label", syncGateLabel());
  renderPosturePanel();
}

function renderPosturePanel() {
  const posture = computePosture();
  // Battery slider
  const slider = document.getElementById("battery-slider");
  const sliderPct = document.getElementById("battery-slider-pct");
  if (slider && sliderPct) {
    slider.value = Math.round(laptopBattery);
    sliderPct.textContent = `${Math.round(laptopBattery)}%`;
    const cls = laptopBattery < 15 ? "low" : laptopBattery < 40 ? "warn" : "";
    slider.className = cls;
    sliderPct.className = `slider-pct ${cls}`;
    if (cls === "low") sliderPct.textContent = `${Math.round(laptopBattery)}% CRIT`;
    else if (cls === "warn") sliderPct.textContent = `${Math.round(laptopBattery)}% LOW`;
  }
  // Posture metrics
  setText("#posture-battery-pct", `${Math.round(laptopBattery)}%`);
  setText("#posture-runtime", `${Math.round(posture.runtimeMin)} min`);
  setText("#posture-tier", displayTier(posture.tier).toUpperCase());
  setText("#posture-thermal", posture.thermal.charAt(0).toUpperCase() + posture.thermal.slice(1));
  setText("#posture-fallback", posture.tier !== "minimal" ? "Software" : "Limited");
  // Battery bar
  const bar = document.getElementById("posture-battery-bar");
  if (bar) {
    bar.style.width = `${Math.max(0, laptopBattery)}%`;
    bar.style.background = laptopBattery < 15 ? "var(--danger)" : laptopBattery < 40 ? "var(--warn)" : "var(--accent)";
  }
  // Tier label color
  const tierEl = document.getElementById("posture-tier");
  if (tierEl) {
    tierEl.className = `tier-label ${posture.tier}`;
  }
  // Workloads
  document.querySelector("#posture-workloads").innerHTML = [
    ...posture.safe.map((w) => `<span class="workload-tag safe">${w}</span>`),
    ...posture.restricted.map((w) => `<span class="workload-tag restricted">${w}</span>`),
  ].join("");
  // Notes
  document.querySelector("#posture-notes").innerHTML = posture.notes
    .map((note) => `<div class="posture-note ${note.level || ""}">${note.text}</div>`)
    .join("");
}

function tick(now) {
  const dt = Math.min(0.08, (now - lastTick) / 1000);
  lastTick = now;
  stepSimulation(dt);
  renderFrame();
  requestAnimationFrame(tick);
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function wrapAngle(angle) {
  return Math.atan2(Math.sin(angle), Math.cos(angle));
}

function setActiveView(view) {
  document.querySelectorAll(".view-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === view);
  });
  document.querySelectorAll("[data-view-panel]").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.viewPanel === view);
  });
  pushLog(`View Switched To ${view === "overview" ? "Overview" : "Field C2"}.`);
  renderFrame();
}

function triggerSync() {
  // Hard boundary: even if button is somehow clicked, enforce the gate
  if (connectivityMode !== "online") {
    pushLog(`Sync Blocked: ${CONNECTIVITY_LABELS[connectivityMode]} Prevents Enterprise Upload.`);
    document.querySelector("#sync-status").textContent = `Sync Blocked: ${CONNECTIVITY_LABELS[connectivityMode]} Prevents Enterprise Upload`;
    return;
  }
  if (stagedCommands.length === 0) {
    pushLog("No Staged Commands To Sync.");
    return;
  }
  const count = stagedCommands.length;
  stagedCommands.length = 0;
  spoolDepth = 0;
  syncStaged = false;
  pushLog(`${count} Commands Released Via Operator Sync Gate.`);
  document.querySelector("#sync-status").textContent = `Released ${count} Commands At T+${simTime.toFixed(1)}s`;
  setTimeout(() => {
    document.querySelector("#sync-status").textContent = "No Connection Required For Local Operations";
  }, 3000);
}

document.querySelector("#resume-mission").addEventListener("click", () => issueCommand("resume"));
document.querySelector("#patrol-area").addEventListener("click", () => issueCommand("patrol"));
document.querySelector("#return-home").addEventListener("click", () => issueCommand("return"));
document.querySelector("#hold-position").addEventListener("click", () => issueCommand("hold"));
document.querySelector("#emergency-stop").addEventListener("click", () => issueCommand("abort"));
document.querySelector("#sync-now").addEventListener("click", () => triggerSync());
document.querySelectorAll(".view-tab").forEach((button) => {
  button.addEventListener("click", () => setActiveView(button.dataset.view));
});
povCanvas.addEventListener("pointerdown", handlePovPointerDown);
povCanvas.addEventListener("pointermove", handlePovPointerMove);
povCanvas.addEventListener("pointerup", handlePovPointerUp);
povCanvas.addEventListener("pointerleave", () => {
  fieldView.dragging = false;
});
povCanvas.addEventListener("wheel", handlePovWheel, { passive: false });

function setConnectivityMode(mode) {
  connectivityMode = mode;
  if (mode === "offline") {
    pushLog("Mode Offline: Local C2 Active, Enterprise Sync Blocked.");
  } else if (mode === "degraded") {
    pushLog("Mode Degraded: Local C2 Active, Sync Queue Held, Awaiting Connectivity.");
  } else {
    pushLog("Mode Online: Enterprise Sync Gate Open.");
  }
  renderFrame();
}

document.querySelector("#mode-offline").addEventListener("click", () => setConnectivityMode("offline"));
document.querySelector("#mode-degraded").addEventListener("click", () => setConnectivityMode("degraded"));
document.querySelector("#mode-online").addEventListener("click", () => setConnectivityMode("online"));

// Power source buttons
document.querySelectorAll(".power-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    powerSource = btn.dataset.source;
    document.querySelectorAll(".power-btn").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    renderFrame();
  });
});

// Battery slider handler
const batterySlider = document.getElementById("battery-slider");
if (batterySlider) {
  batterySlider.addEventListener("input", (e) => {
    laptopBattery = parseFloat(e.target.value);
    renderFrame();
  });
}

pushLog("Fusion Node Started; Laptop-Local Authority Active.");
requestAnimationFrame(tick);
