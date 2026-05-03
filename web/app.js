const WORLD_M = 1200;
const AOI_TILE = {
  label: "1.2 km local AOI",
  cropX: 0.31,
  cropY: 0.43,
  cropScale: 0.18,
  meshStepM: 120,
};
const BASE = { x: 120, y: 850 };
const colors = {
  alpha: "#55d6a6",
  bravo: "#79b8ff",
  charlie: "#ff5d5d",
  delta: "#e6c35c",
  team: "#d8e0dc",
};

const earthImagery = {
  src: "../assets/visual/earth/blue_marble_january_5400.jpg",
  image: new Image(),
  ready: false,
  failed: false,
};

const hazards = [
  { id: "rf-denial-east", label: "RF denial", x: 610, y: 360, r: 105, severity: "critical" },
  { id: "return-corridor", label: "return corridor", x: 330, y: 790, r: 95, severity: "watch" },
  { id: "terrain-mask", label: "terrain mask", x: 760, y: 650, r: 82, severity: "watch" },
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

let selectedId = "uav-alpha";
let connectivityMode = "offline";
let rayPath = "cpu";
let simPaused = false;
let simTime = 0;
let lastTick = performance.now();
let commandSeq = 1;
const stagedCommands = [];  // commands staged for sync
const missionLog = [];
let spoolDepth = 0;         // offline spool buffer depth
let syncWatermark = 0;      // timestamp of last staged sync
let syncStaged = false;     // whether a packet is staged for gate

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
    if (runtimeMin < 30) notes.push({ text: `BATTERY CRITICAL: ~${Math.round(runtimeMin)} min — switch to backpack or AC`, level: "critical" });
    else if (runtimeMin < 60) notes.push({ text: `BATTERY LOW: ~${Math.round(runtimeMin)} min remaining`, level: "warn" });
    else notes.push({ text: `Battery: ~${Math.round(runtimeMin)} min estimated runtime`, level: "" });
  } else if (powerSource === "backpack_generator") {
    notes.push({ text: "Backpack generator active — extended runtime", level: "" });
  } else {
    notes.push({ text: "AC mains — no runtime constraint", level: "" });
  }
  if (tier === "minimal") notes.push({ text: "MINIMAL: only C2, spool, alerting active", level: "critical" });
  else if (tier === "reduced") notes.push({ text: "REDUCED: heavy batch workloads paused", level: "warn" });
  if (thermal === "hot") notes.push({ text: "Thermal throttle: CPU load elevated", level: "warn" });
  if (connectivityMode === "offline") notes.push({ text: "OFFLINE: enterprise sync blocked, local C2 is authority", level: "" });
  else if (connectivityMode === "degraded") notes.push({ text: "DEGRADED: sync queued, awaiting connectivity", level: "" });

  return { tier, thermal, runtimeMin, safe, restricted, notes };
}

const CONNECTIVITY_LABELS = {
  offline: "FUSION NODE AUTHORITY",
  degraded: "LOCAL C2 ACTIVE",
  online: "ENTERPRISE SYNC ENABLED",
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

function selectedFeed() {
  return feeds.find((f) => f.id === selectedId) || feeds[0];
}

function pushLog(text) {
  missionLog.unshift(`T+${simTime.toFixed(1)}s ${text}`);
  missionLog.splice(8);
}

function issueCommand(command) {
  const feed = selectedFeed();
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

  spoolDepth = stagedCommands.length;
  syncStaged = spoolDepth > 0;
  if (syncStaged) {
    syncWatermark = simTime;
  }

  if (command === "return") {
    feed.command = "return";
    feed.target = { ...BASE };
  } else if (command === "hold") {
    feed.command = "hold";
  } else if (command === "patrol") {
    feed.command = "patrol";
    feed.target = { x: 680, y: 360 };
  } else if (command === "abort") {
    feeds.forEach((item) => {
      item.command = "hold";
    });
  } else if (command === "resume") {
    feed.command = "patrol";
  }
  pushLog(`${record.callsign} ${command.toUpperCase()} staged for sync.`);
}

function stepSimulation(dt) {
  if (simPaused) return;
  simTime += dt;

  // drift feed quality metrics over time
  for (const feed of feeds) {
    feed.freshness = Math.max(0.4, Math.min(1.0, feed.freshness + (Math.random() - 0.5) * 0.02));
    feed.confidence = Math.max(0.3, Math.min(0.99, feed.confidence + (Math.random() - 0.5) * 0.03));
    feed.latency = Math.max(20, Math.min(300, feed.latency + (Math.random() - 0.5) * 10));
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

    if (feed.command === "patrol" || feed.command === "relay" || feed.command === "overwatch") {
      feed.orbitPhase += dt * 0.22;
      const center = feed.target;
      const radius = feed.command === "relay" ? 230 : feed.command === "overwatch" ? 150 : 180;
      feed.target = {
        x: center.x + Math.cos(feed.orbitPhase) * radius * 0.012,
        y: center.y + Math.sin(feed.orbitPhase) * radius * 0.012,
      };
    }

    const spatialHits = bvhQuery(feed);
    const avoidance = spatialHits.find((hit) => hit.kind === "hazard" && hit.distance < hit.radius + 35);
    const terrainConflict = spatialHits.find((hit) => hit.kind === "terrain" && hit.distance < hit.radius);
    const target = avoidance
      ? {
          x: feed.x + (feed.x - avoidance.x) * 0.8,
          y: feed.y + (feed.y - avoidance.y) * 0.8,
        }
      : feed.target;
    moveToward(feed, target, dt, avoidance || terrainConflict);
  }
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
      label: "terrain clearance",
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
  for (const other of allFeeds()) {
    if (other.id === asset.id) continue;
    const distance = Math.hypot(asset.x - other.x, asset.y - other.y);
    if (distance < 155) {
      hits.push({ ...other, kind: "asset", distance, radius: 28 });
    }
  }
  return hits.sort((a, b) => a.distance - b.distance);
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
    sensor: "object pass",
  };
}

function classifyFrame(feed, visible) {
  const objectCount = visible.length;
  const airCount = visible.filter((obj) => obj.type !== "ground").length;
  const avgConfidence = objectCount
    ? visible.reduce((sum, obj) => sum + obj.detectionConfidence, 0) / objectCount
    : 0;
  if (visible.some((obj) => obj.threat === "critical")) {
    return [
      ["restricted object quantified", 0.92],
      ["objects quantified", Math.max(0.48, avgConfidence)],
      ["air tracks detected", clamp(airCount / Math.max(1, feeds.length), 0.16, 0.98)],
    ];
  }
  if (feed.battery < 70) {
    return [
      ["low power track quantified", 0.84],
      ["objects quantified", Math.max(0.45, avgConfidence)],
      ["air tracks detected", clamp(airCount / Math.max(1, feeds.length), 0.16, 0.98)],
    ];
  }
  return [
    ["objects quantified", Math.max(0.55, avgConfidence)],
    ["air tracks detected", clamp(airCount / Math.max(1, feeds.length), 0.16, 0.98)],
    ["range and altitude labels", objectCount ? 0.91 : 0.12],
  ];
}

function visibleObjects(feed) {
  const objects = [];
  const detectionRangeM = 650;
  for (const target of allFeeds()) {
    if (target.id === feed.id) continue;
    const dx = target.x - feed.x;
    const dy = target.y - feed.y;
    const distance = Math.hypot(dx, dy);
    if (distance > detectionRangeM) continue;
    const angle = Math.atan2(dy, dx);
    const heading = (feed.heading * Math.PI) / 180;
    const delta = wrapAngle(angle - heading);
    const threat = bvhQuery(target).some((hit) => hit.severity === "critical" && hit.distance < hit.radius)
      ? "critical"
      : "watch";
    const detectionConfidence = clamp(
      target.confidence * 0.62 + target.freshness * 0.24 + (target.type === "ground" ? 0.08 : 0.12) - distance / 2600,
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
    });
  }
  return objects.sort((a, b) => a.range - b.range);
}

function resizeCanvas(canvas) {
  const bounds = canvas.parentElement.getBoundingClientRect();
  canvas.width = Math.max(480, Math.floor(bounds.width));
  canvas.height = Math.max(340, Math.floor(bounds.height));
}

function worldToCanvas(asset, width, height) {
  return { x: (asset.x / WORLD_M) * width, y: (asset.y / WORLD_M) * height };
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
  if (earthImagery.ready) {
    drawEarthAoiTile(ctx, earthImagery.image, width, height);
    const shade = ctx.createLinearGradient(0, 0, width, height);
    shade.addColorStop(0, "rgba(6, 12, 14, 0.18)");
    shade.addColorStop(0.55, "rgba(19, 38, 31, 0.46)");
    shade.addColorStop(1, "rgba(5, 8, 9, 0.72)");
    ctx.fillStyle = shade;
    ctx.fillRect(0, 0, width, height);
  } else {
    drawProceduralTerrain(ctx, width, height);
  }

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

function drawContourOverlay(ctx, width, height) {
  ctx.save();
  ctx.globalAlpha = earthImagery.ready ? 0.42 : 1;
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
  const scaleM = 250;
  const barW = (scaleM / WORLD_M) * width;
  const x = width - barW - 28;
  const y = height - 28;
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
  ctx.fillText(AOI_TILE.label, x - 2, y + 22);
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
  ctx.strokeStyle = "rgba(230,195,92,0.58)";
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(width * 0.05, height * 0.82);
  ctx.bezierCurveTo(width * 0.24, height * 0.72, width * 0.32, height * 0.52, width * 0.48, height * 0.5);
  ctx.bezierCurveTo(width * 0.68, height * 0.48, width * 0.8, height * 0.36, width * 0.96, height * 0.31);
  ctx.stroke();

  ctx.strokeStyle = "rgba(245,241,232,0.26)";
  ctx.lineWidth = 1.4;
  ctx.beginPath();
  ctx.moveTo(width * 0.18, height * 0.94);
  ctx.lineTo(width * 0.36, height * 0.66);
  ctx.lineTo(width * 0.58, height * 0.56);
  ctx.stroke();
}

function drawSwarmMap() {
  resizeCanvas(swarmCanvas);
  const width = swarmCanvas.width;
  const height = swarmCanvas.height;
  const ctx = swarmCtx;
  ctx.clearRect(0, 0, width, height);
  drawTerrainBackdrop(ctx, width, height);
  drawRoadNetwork(ctx, width, height);

  for (const node of buildBvhNodes()) {
    ctx.strokeStyle = node.severity === "critical" ? "rgba(255, 93, 93, 0.42)" : "rgba(230, 195, 92, 0.35)";
    ctx.lineWidth = 1;
    ctx.strokeRect((node.x / WORLD_M) * width, (node.y / WORLD_M) * height, (node.w / WORLD_M) * width, (node.h / WORLD_M) * height);
  }

  for (const hazard of hazards) {
    drawZone(ctx, (hazard.x / WORLD_M) * width, (hazard.y / WORLD_M) * height, (hazard.r / WORLD_M) * width, hazard.severity === "critical" ? "#6d3238" : "#65551f", hazard.label);
  }

  drawBase(ctx, width, height);
  for (const feed of feeds) {
    drawPath(ctx, feed, width, height);
  }
  for (const asset of allFeeds()) {
    drawAsset(ctx, asset, width, height);
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
  ctx.fillText("fusion node", point.x + 16, point.y + 4);
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

function drawAsset(ctx, asset, width, height) {
  const { x, y } = worldToCanvas(asset, width, height);
  const color = colors[asset.key] || "#f2efe5";
  const selected = asset.id === selectedId;
  ctx.fillStyle = color;
  ctx.strokeStyle = selected ? "#f2efe5" : "#10171b";
  ctx.lineWidth = selected ? 3 : 2;
  ctx.beginPath();
  if (asset.type === "ground") {
    ctx.rect(x - 8, y - 5, 16, 10);
  } else {
    ctx.arc(x, y, selected ? 10 : 7, 0, Math.PI * 2);
  }
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#f2efe5";
  ctx.font = "12px Inter, Arial";
  ctx.fillText(asset.callsign, x + 12, y + 4);
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
  drawPovHazards(feed, width, height);
  drawPovDetectionFrustum(feed, width, height);
  drawPovObjects(feed, visible, width, height);
  drawPovTelemetry(feed, visible, width, height);
  drawPovQuantificationPanel(visible, width, height);
}

function detectionClass(asset) {
  if (asset.type === "ground") return "ground team";
  if (asset.type === "fixed-wing") return "fixed wing";
  return "quadrotor";
}

function mapProjectionScale(width, height) {
  return Math.min(width, height) / 975;
}

function projectPovMapPoint(feed, point, width, height, zRelativeM = 0) {
  const scale = mapProjectionScale(width, height);
  const dx = point.x - feed.x;
  const dy = point.y - feed.y;
  return {
    x: width * 0.5 + (dx - dy) * scale * 0.66,
    y: height * 0.57 + (dx + dy) * scale * 0.34 - zRelativeM * 0.42,
  };
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
  const extent = 720;
  const step = 120;

  povCtx.save();
  povCtx.lineWidth = 1;
  for (let offset = -extent; offset <= extent; offset += step) {
    const major = offset % 240 === 0;
    povCtx.strokeStyle = major ? "rgba(245, 241, 232, 0.2)" : "rgba(245, 241, 232, 0.1)";

    povCtx.beginPath();
    for (let u = -extent; u <= extent; u += step / 2) {
      const point = { x: feed.x + u, y: feed.y + offset };
      const projected = projectPovMapPoint(
        feed,
        point,
        width,
        height,
        terrainHeightAt(point.x, point.y) - feed.z,
      );
      if (u === -extent) povCtx.moveTo(projected.x, projected.y);
      else povCtx.lineTo(projected.x, projected.y);
    }
    povCtx.stroke();

    povCtx.beginPath();
    for (let v = -extent; v <= extent; v += step / 2) {
      const point = { x: feed.x + offset, y: feed.y + v };
      const projected = projectPovMapPoint(
        feed,
        point,
        width,
        height,
        terrainHeightAt(point.x, point.y) - feed.z,
      );
      if (v === -extent) povCtx.moveTo(projected.x, projected.y);
      else povCtx.lineTo(projected.x, projected.y);
    }
    povCtx.stroke();
  }
  povCtx.restore();
}

function drawPovHazards(feed, width, height) {
  const scale = mapProjectionScale(width, height);
  for (const hazard of hazards) {
    const distance = Math.hypot(hazard.x - feed.x, hazard.y - feed.y);
    if (distance > 780) continue;
    const projected = projectPovMapPoint(
      feed,
      hazard,
      width,
      height,
      terrainHeightAt(hazard.x, hazard.y) - feed.z,
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
  const origin = projectPovMapPoint(feed, feed, width, height, 0);
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
  const leftProjected = projectPovMapPoint(feed, left, width, height, -feed.z * 0.35);
  const rightProjected = projectPovMapPoint(feed, right, width, height, -feed.z * 0.35);

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
  const selected = {
    ...feed,
    range: 0,
    bearingDeg: 0,
    altitudeDelta: 0,
    className: "selected node",
    detectionConfidence: 1,
    threat: "watch",
  };
  const mapObjects = [selected, ...visible];
  const sorted = mapObjects
    .map((obj) => ({
      ...obj,
      ground: projectPovMapPoint(
        feed,
        obj,
        width,
        height,
        terrainHeightAt(obj.x, obj.y) - feed.z,
      ),
      air: projectPovMapPoint(feed, obj, width, height, obj.z - feed.z),
    }))
    .sort((a, b) => a.ground.y - b.ground.y);

  for (const obj of sorted) {
    drawPovObjectMarker(obj);
    if (obj.id !== feed.id) {
      addDetectionLabel(obj, width, height);
    }
  }
}

function drawPovObjectMarker(obj) {
  const color = obj.id === selectedId ? "#f5f1e8" : colors[obj.key] || "#55d6a6";
  const markerRadius = obj.type === "ground" ? 8 : 11;
  const critical = obj.threat === "critical";

  povCtx.save();
  povCtx.strokeStyle = critical ? "#ff5d5d" : "rgba(245, 241, 232, 0.78)";
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
  povCtx.strokeStyle = critical ? "#ff5d5d" : "#f5f1e8";
  povCtx.lineWidth = critical ? 3 : 2;
  povCtx.beginPath();
  if (obj.type === "ground") {
    povCtx.rect(obj.air.x - markerRadius, obj.air.y - markerRadius / 2, markerRadius * 2, markerRadius);
  } else if (obj.type === "fixed-wing") {
    povCtx.moveTo(obj.air.x, obj.air.y - markerRadius);
    povCtx.lineTo(obj.air.x + markerRadius * 1.8, obj.air.y + markerRadius * 0.8);
    povCtx.lineTo(obj.air.x, obj.air.y + markerRadius * 0.25);
    povCtx.lineTo(obj.air.x - markerRadius * 1.8, obj.air.y + markerRadius * 0.8);
    povCtx.closePath();
  } else {
    povCtx.arc(obj.air.x, obj.air.y, markerRadius, 0, Math.PI * 2);
  }
  povCtx.fill();
  povCtx.stroke();

  if (obj.id !== selectedId) {
    const boxW = obj.type === "ground" ? 42 : 54;
    const boxH = obj.type === "ground" ? 24 : 34;
    povCtx.strokeStyle = critical ? "rgba(255, 93, 93, 0.9)" : "rgba(85, 214, 166, 0.86)";
    povCtx.setLineDash([7, 5]);
    povCtx.strokeRect(obj.air.x - boxW / 2, obj.air.y - boxH / 2, boxW, boxH);
    povCtx.setLineDash([]);
  }
  povCtx.restore();
}

function addDetectionLabel(obj, width, height) {
  const label = document.createElement("div");
  label.className = `target-label ${obj.threat}`;
  label.style.left = `${clamp(obj.air.x, 10, width - 190)}px`;
  label.style.top = `${clamp(obj.air.y, 28, height - 62)}px`;

  const title = document.createElement("strong");
  title.textContent = `${obj.className} ${Math.round(obj.detectionConfidence * 100)}%`;
  const details = document.createElement("span");
  details.textContent = `${obj.callsign} · ${obj.range} m · delta ${obj.altitudeDelta} m`;
  label.append(title, details);
  overlay.appendChild(label);
}

function drawPovTelemetry(feed, visible, width, height) {
  povCtx.fillStyle = "rgba(10, 15, 18, 0.62)";
  povCtx.fillRect(18, 18, 260, 78);
  povCtx.fillStyle = "#f2efe5";
  povCtx.font = "14px Inter, Arial";
  povCtx.fillText(`${feed.callsign} 3D OBJECT MAP`, 32, 42);
  povCtx.fillText(`CUE ${visible.length}  HDG ${Math.round((feed.heading + 360) % 360)}  ALT ${formatMeters(feed.z)}`, 32, 66);
  povCtx.fillText(`SPD ${Math.round(feed.speed)} m/s  BAT ${Math.round(feed.battery)}%`, 32, 90);
}

function drawPovQuantificationPanel(visible, width, height) {
  const avgConfidence = visible.length
    ? visible.reduce((sum, obj) => sum + obj.detectionConfidence, 0) / visible.length
    : 0;
  const airTracks = visible.filter((obj) => obj.type !== "ground").length;
  const panelWidth = 228;
  const x = width - panelWidth - 18;
  const y = 18;
  povCtx.save();
  povCtx.fillStyle = "rgba(8, 13, 15, 0.68)";
  povCtx.strokeStyle = "rgba(85, 214, 166, 0.36)";
  povCtx.lineWidth = 1;
  povCtx.beginPath();
  povCtx.roundRect(x, y, panelWidth, 82, 8);
  povCtx.fill();
  povCtx.stroke();

  povCtx.fillStyle = "#55d6a6";
  povCtx.font = "12px Inter, Arial";
  povCtx.fillText("OBJECT PASS", x + 14, y + 24);
  povCtx.fillStyle = "#f5f1e8";
  povCtx.font = "20px Inter, Arial";
  povCtx.fillText(`${visible.length} quantified`, x + 14, y + 50);
  povCtx.fillStyle = "rgba(245, 241, 232, 0.72)";
  povCtx.font = "12px Inter, Arial";
  povCtx.fillText(
    `${airTracks} air tracks · ${Math.round(avgConfidence * 100)}% avg confidence`,
    x + 14,
    y + 70,
  );
  povCtx.restore();
}

function renderFeeds() {
  document.querySelector("#asset-list").innerHTML = allFeeds()
    .map((feed) => {
      const hit = bvhQuery(feed).find((item) => item.severity === "critical" && item.distance < item.radius);
      const dotClass = hit ? "critical" : feed.battery < 70 ? "warn" : "";
      const selected = feed.id === selectedId ? "selected" : "";
      const latClass = latencyClass(feed.latency);
      const latency = formatLatencyMs(feed.latency);
      return `<button class="asset-row ${selected}" data-feed="${feed.id}">
        <div>
          <strong>${feed.callsign}</strong>
          <div class="asset-meta">${feed.command} · ${formatMeters(feed.z)} · ${Math.round(feed.battery)}% · <span class="feed-latency compact ${latClass}">${latency}</span></div>
        </div>
        <span class="asset-dot ${dotClass}"></span>
      </button>`;
    })
    .join("");
  document.querySelectorAll(".asset-row").forEach((row) => {
    row.addEventListener("click", () => {
      selectedId = row.dataset.feed;
      renderFrame();
    });
  });
}

function renderFeedQuality() {
  const all = allFeeds();
  const avgFresh = all.reduce((s, f) => s + f.freshness, 0) / all.length;
  const freshnessLabel = avgFresh > 0.85 ? "fresh" : avgFresh > 0.6 ? "degraded" : "stale";
  document.querySelector("#feed-count").textContent = `${feeds.length} feeds`;
  document.querySelector("#feed-freshness").textContent = freshnessLabel;
  document.querySelector("#spool-depth").textContent = `spool ${spoolDepth}`;

  document.querySelector("#feed-quality").innerHTML = allFeeds()
    .map((feed) => {
      const freshPct = Math.round(feed.freshness * 100);
      const confPct = Math.round(feed.confidence * 100);
      const latClass = latencyClass(feed.latency);
      const latency = formatLatencyMs(feed.latency);
      return `<div class="feed-row">
        <div class="feed-header"><strong>${feed.callsign}</strong><span class="feed-latency ${latClass}">${latency}</span></div>
        <div class="feed-metrics">
          <div class="metric-bar"><span class="metric-label">Fresh</span><div class="bar-track"><span class="bar-fill" style="width:${freshPct}%"></span></div></div>
          <div class="metric-bar"><span class="metric-label">Conf</span><div class="bar-track"><span class="bar-fill" style="width:${confPct}%"></span></div></div>
        </div>
      </div>`;
    })
    .join("");
}

function renderStagedPacket() {
  const packetEl = document.querySelector("#staged-packet");
  if (stagedCommands.length === 0) {
    packetEl.innerHTML = '<div class="packet-empty subtle">No staged commands — local C2 issues commands directly</div>';
    return;
  }
  packetEl.innerHTML = stagedCommands
    .slice(0, 5)
    .map((cmd) => `<div class="packet-item"><span class="packet-id">${cmd.id}</span><span class="packet-cmd">${cmd.callsign} ${cmd.command.toUpperCase()}</span><span class="packet-ts">T+${cmd.ts.toFixed(1)}s</span></div>`)
    .join("");
}

function renderHardware(feed, hits) {
  const status = modeCopy();
  const bvhMs = 8.8 + hits.length * 0.7;
  const rows = [
    ["Fusion authority", "laptop-local sensor fusion", "good"],
    ["Earth AOI", earthImagery.ready ? "cached raster tile" : "procedural estimate", earthImagery.ready ? "good" : "watch"],
    ["Terrain mesh", `${terrainTriangleCount()} triangles`, "good"],
    ["Collision BVH", `${hits.length} checks · ${formatLatencyMs(bvhMs)}`, "good"],
    ["Spool buffer", `${spoolDepth} staged for gate`, spoolDepth > 0 ? "watch" : "good"],
    ["Sync watermark", `T+${syncWatermark.toFixed(1)}s`, spoolDepth > 0 ? "watch" : "good"],
  ];
  document.querySelector("#hardware-list").innerHTML = rows
    .map(
      ([name, detail, kind]) =>
        `<div class="status-row"><div><strong>${name}</strong><div class="status-detail">${detail}</div></div><span class="status-chip ${kind}">${kind}</span></div>`,
    )
    .join("");
  setText("#bvh-label", "CPU route check");
  setText("#fusion-badge", "CPU collision parity");
  setText(
    "#map-hud-copy",
    earthImagery.ready
      ? `${AOI_TILE.label}; terrain mesh feeds maneuver BVH`
      : "Terrain from procedural estimate; awaiting cache",
  );
  setText("#range-label", `${Math.round(Math.max(0, ...hits.map((hit) => hit.distance)))} m`);
  setText("#pov-title", `${feed.callsign} 3D Map Feed`);
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
  if (critical) {
    alerts.push(["critical", `${feed.callsign} inside ${critical.label}; route correction active`]);
  } else if (scores[0][0] === "restricted volume in POV") {
    alerts.push(["critical", "Restricted volume in view"]);
  }
  if (spoolDepth > 0) {
    alerts.push(["watch", `${spoolDepth} commands queued for operator sync gate`]);
  }
  if (feed.battery < 70) alerts.push(["watch", `${feed.callsign} battery near return threshold`]);
  if (alerts.length === 0) alerts.push(["watch", "Fusion node nominal"]);
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
  setText("#sync-watermark", `watermark T+${status.watermark.toFixed(1)}s`);
  setText("#clock-label", `T+${simTime.toFixed(1)}s`);
  const syncPill = document.querySelector("#sync-state-pill");
  if (syncPill) {
    syncPill.textContent = spoolDepth > 0 ? `${spoolDepth} staged` : "sync idle";
    syncPill.classList.toggle("staged", spoolDepth > 0);
  }
  // Sync gate: disable release button unless in ONLINE mode
  const syncBtn = document.querySelector("#sync-now");
  if (syncBtn) {
    syncBtn.disabled = connectivityMode !== "online";
    syncBtn.title = connectivityMode === "online"
      ? "Release staged commands to enterprise"
      : `${connectivityMode.toUpperCase()} mode: enterprise sync blocked`;
  }
  // Update operator-gated copy based on mode
  const syncStatus = document.querySelector("#sync-status");
  if (syncStatus) {
    if (connectivityMode === "offline") {
      syncStatus.textContent = "OFFLINE: sync gate closed · enterprise unreachable";
    } else if (connectivityMode === "degraded") {
      syncStatus.textContent = "DEGRADED: sync gate closed · commands queued for reconnect";
    } else {
      syncStatus.textContent = "ONLINE: sync gate open · press Release to sync";
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

function renderFrame() {
  const feed = selectedFeed();
  const visible = visibleObjects(feed);
  const hits = bvhQuery(feed);
  const scores = classifyFrame(feed, visible);
  drawSwarmMap();
  drawPov(feed, visible);
  renderFeeds();
  renderFeedQuality();
  renderStagedPacket();
  renderHardware(feed, hits);
  renderVision(scores);
  renderAlerts(feed, hits, scores);
  renderMissionLog();
  updateModeChrome();
  document.querySelector("#frame-counter").textContent = simPaused
    ? "Paused"
    : "3D local object map with detector object quantification";
  document.querySelector("#field-condition-label").textContent = scores[0][0];
  document.querySelector("#npu-label").textContent = modeCopy().sensor;
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

function cycleSelected(offset) {
  const all = allFeeds();
  const current = Math.max(0, all.findIndex((a) => a.id === selectedId));
  const next = (current + offset + all.length) % all.length;
  selectedId = all[next].id;
  pushLog(`Selected feed switched to ${all[next].callsign}.`);
  renderFrame();
}

function triggerSync() {
  // Hard boundary: even if button is somehow clicked, enforce the gate
  if (connectivityMode !== "online") {
    pushLog(`SYNC BLOCKED: ${connectivityMode.toUpperCase()} mode — enterprise sync requires ONLINE.`);
    document.querySelector("#sync-status").textContent = `SYNC BLOCKED: ${connectivityMode.toUpperCase()} mode prevents enterprise upload`;
    return;
  }
  if (stagedCommands.length === 0) {
    pushLog("No staged commands to sync.");
    return;
  }
  const count = stagedCommands.length;
  stagedCommands.length = 0;
  spoolDepth = 0;
  syncStaged = false;
  pushLog(`${count} commands released via operator sync gate.`);
  document.querySelector("#sync-status").textContent = `Released ${count} commands at T+${simTime.toFixed(1)}s`;
  setTimeout(() => {
    document.querySelector("#sync-status").textContent = "No connection required for local operations";
  }, 3000);
}

document.querySelector("#resume-mission").addEventListener("click", () => issueCommand("resume"));
document.querySelector("#patrol-area").addEventListener("click", () => issueCommand("patrol"));
document.querySelector("#return-home").addEventListener("click", () => issueCommand("return"));
document.querySelector("#hold-position").addEventListener("click", () => issueCommand("hold"));
document.querySelector("#emergency-stop").addEventListener("click", () => issueCommand("abort"));
document.querySelector("#sync-now").addEventListener("click", () => triggerSync());
document.querySelector("#prev-frame").addEventListener("click", () => cycleSelected(-1));
document.querySelector("#next-frame").addEventListener("click", () => cycleSelected(1));
document.querySelector("#toggle-bvh").addEventListener("click", () => {
  rayPath = rayPath === "rtx" ? "cpu" : "rtx";
  pushLog(
    `Collision/path solver switched to ${rayPath === "rtx" ? "RT core acceleration" : "CPU parity"} locally.`,
  );
});

function setConnectivityMode(mode) {
  connectivityMode = mode;
  if (mode === "offline") {
    pushLog("Mode OFFLINE: Local C2 active, enterprise sync blocked.");
  } else if (mode === "degraded") {
    pushLog("Mode DEGRADED: Local C2 active, sync queue held, awaiting connectivity.");
  } else {
    pushLog("Mode ONLINE: Enterprise sync gate open.");
  }
  renderFrame();
}

document.querySelector("#mode-offline").addEventListener("click", () => setConnectivityMode("offline"));
document.querySelector("#mode-degraded").addEventListener("click", () => setConnectivityMode("degraded"));
document.querySelector("#mode-online").addEventListener("click", () => setConnectivityMode("online"));

pushLog("Fusion node started; laptop-local authority active.");
requestAnimationFrame(tick);
