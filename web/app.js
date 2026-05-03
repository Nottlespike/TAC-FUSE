const WORLD_M = 1000;
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

const drones = [
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
    target: { x: 690, y: 330 },
    orbitPhase: 0.1,
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
    target: { x: 780, y: 500 },
    orbitPhase: 1.4,
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
    target: { x: 505, y: 470 },
    orbitPhase: 2.2,
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
    target: { x: 640, y: 610 },
    orbitPhase: 3.1,
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
};

let selectedId = "uav-alpha";
let connectivityMode = "offline";
let rayPath = "rtx";
let simPaused = false;
let simTime = 0;
let lastTick = performance.now();
let commandSeq = 1;
const commandQueue = [];
const missionLog = [];

const swarmCanvas = document.querySelector("#swarm-map");
const swarmCtx = swarmCanvas.getContext("2d");
const povCanvas = document.querySelector("#pov-canvas");
const povCtx = povCanvas.getContext("2d");
const overlay = document.querySelector("#pov-overlay");

earthImagery.image.onload = () => {
  earthImagery.ready = true;
};
earthImagery.image.onerror = () => {
  earthImagery.failed = true;
};
earthImagery.image.src = earthImagery.src;

function allAssets() {
  return [...drones, groundTeam];
}

function selectedDrone() {
  return drones.find((drone) => drone.id === selectedId) || drones[0];
}

function pushLog(text) {
  missionLog.unshift(`T+${simTime.toFixed(1)}s ${text}`);
  missionLog.splice(5);
}

function issueCommand(command) {
  const drone = selectedDrone();
  const record = {
    id: `cmd-${String(commandSeq).padStart(3, "0")}`,
    assetId: drone.id,
    callsign: drone.callsign,
    command,
    mode: connectivityMode,
    status: "local",
  };
  commandSeq += 1;
  commandQueue.unshift(record);
  commandQueue.splice(8);

  if (command === "return") {
    drone.command = "return";
    drone.target = { ...BASE };
  } else if (command === "hold") {
    drone.command = "hold";
  } else if (command === "patrol") {
    drone.command = "patrol";
    drone.target = { x: 680, y: 360 };
  } else if (command === "abort") {
    drones.forEach((item) => {
      item.command = "hold";
    });
  } else if (command === "resume") {
    drone.command = "patrol";
  }
  pushLog(`${record.callsign} command ${command.toUpperCase()} applied locally.`);
}

function stepSimulation(dt) {
  if (simPaused) return;
  simTime += dt;
  for (const drone of drones) {
    drone.battery = Math.max(35, drone.battery - dt * 0.018);
    if (drone.command === "hold") continue;

    if (drone.command === "patrol" || drone.command === "relay" || drone.command === "overwatch") {
      drone.orbitPhase += dt * 0.22;
      const center = drone.target;
      const radius = drone.command === "relay" ? 230 : drone.command === "overwatch" ? 150 : 180;
      drone.target = {
        x: center.x + Math.cos(drone.orbitPhase) * radius * 0.012,
        y: center.y + Math.sin(drone.orbitPhase) * radius * 0.012,
      };
    }

    const avoidance = bvhQuery(drone).find((hit) => hit.kind === "hazard" && hit.distance < hit.radius + 35);
    const target = avoidance
      ? {
          x: drone.x + (drone.x - avoidance.x) * 0.8,
          y: drone.y + (drone.y - avoidance.y) * 0.8,
        }
      : drone.target;
    moveToward(drone, target, dt);
  }
}

function moveToward(drone, target, dt) {
  const dx = target.x - drone.x;
  const dy = target.y - drone.y;
  const distance = Math.hypot(dx, dy);
  if (distance < 1) return;
  const step = Math.min(distance, drone.speed * dt);
  drone.x += (dx / distance) * step;
  drone.y += (dy / distance) * step;
  drone.heading = (Math.atan2(dy, dx) * 180) / Math.PI;
  drone.x = clamp(drone.x, 40, WORLD_M - 40);
  drone.y = clamp(drone.y, 40, WORLD_M - 40);
}

function bvhQuery(asset) {
  const hits = [];
  for (const hazard of hazards) {
    const distance = Math.hypot(asset.x - hazard.x, asset.y - hazard.y);
    if (distance < hazard.r + 90) {
      hits.push({ ...hazard, kind: "hazard", distance, radius: hazard.r });
    }
  }
  for (const other of allAssets()) {
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
    sync: commandQueue.length,
    foundry: "Maven packet staged",
    npu: "feeds fused locally",
  };
}

function classifyFrame(drone, visible) {
  if (visible.some((obj) => obj.threat === "critical")) {
    return [
      ["restricted volume in POV", 0.92],
      ["dense multi asset formation", 0.49],
      ["clear corridor", 0.06],
    ];
  }
  if (drone.battery < 70) {
    return [
      ["low power return corridor", 0.84],
      ["clear corridor", 0.33],
      ["low altitude clutter", 0.12],
    ];
  }
  return [
    ["clear corridor", 0.88],
    ["dense multi asset formation", 0.31],
    ["reduced visibility field conditions", 0.11],
  ];
}

function visibleObjects(drone) {
  const objects = [];
  const fov = Math.PI * 0.78;
  const heading = (drone.heading * Math.PI) / 180;
  for (const target of allAssets()) {
    if (target.id === drone.id) continue;
    const dx = target.x - drone.x;
    const dy = target.y - drone.y;
    const distance = Math.hypot(dx, dy);
    if (distance > 520) continue;
    const angle = Math.atan2(dy, dx);
    const delta = wrapAngle(angle - heading);
    if (Math.abs(delta) > fov / 2) continue;
    objects.push({
      ...target,
      range: Math.round(distance),
      screenX: 0.5 + delta / fov,
      screenY: clamp(0.56 + (distance / 520) * 0.22 - (target.z - drone.z) / 260, 0.14, 0.88),
      threat: bvhQuery(target).some((hit) => hit.severity === "critical" && hit.distance < hit.radius)
        ? "critical"
        : "watch",
    });
  }
  return objects;
}

function resizeCanvas(canvas) {
  const bounds = canvas.parentElement.getBoundingClientRect();
  canvas.width = Math.max(480, Math.floor(bounds.width));
  canvas.height = Math.max(340, Math.floor(bounds.height));
}

function worldToCanvas(asset, width, height) {
  return { x: (asset.x / WORLD_M) * width, y: (asset.y / WORLD_M) * height };
}

function drawTerrainBackdrop(ctx, width, height) {
  if (earthImagery.ready) {
    drawImageCover(ctx, earthImagery.image, width, height);
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
  for (const drone of drones) {
    drawPath(ctx, drone, width, height);
  }
  for (const asset of allAssets()) {
    drawAsset(ctx, asset, width, height);
  }
  drawRayFan(ctx, selectedDrone(), width, height);
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
  ctx.fillText("base", point.x + 16, point.y + 4);
}

function drawPath(ctx, drone, width, height) {
  if (!drone.target) return;
  const start = worldToCanvas(drone, width, height);
  const end = worldToCanvas(drone.target, width, height);
  ctx.strokeStyle = drone.id === selectedId ? "rgba(85, 214, 166, 0.64)" : "rgba(121, 184, 255, 0.22)";
  ctx.setLineDash([5, 5]);
  ctx.beginPath();
  ctx.moveTo(start.x, start.y);
  ctx.lineTo(end.x, end.y);
  ctx.stroke();
  ctx.setLineDash([]);
}

function drawRayFan(ctx, drone, width, height) {
  const origin = worldToCanvas(drone, width, height);
  const heading = (drone.heading * Math.PI) / 180;
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

function drawPov(drone, visible) {
  resizeCanvas(povCanvas);
  const width = povCanvas.width;
  const height = povCanvas.height;
  const horizon = Math.floor(height * 0.42);

  const sky = povCtx.createLinearGradient(0, 0, 0, horizon);
  sky.addColorStop(0, "#101923");
  sky.addColorStop(1, "#263e4a");
  povCtx.fillStyle = sky;
  povCtx.fillRect(0, 0, width, horizon);

  const terrain = povCtx.createLinearGradient(0, horizon, 0, height);
  terrain.addColorStop(0, "#2a3625");
  terrain.addColorStop(1, "#121812");
  povCtx.fillStyle = terrain;
  povCtx.fillRect(0, horizon, width, height - horizon);

  if (earthImagery.ready) {
    povCtx.save();
    povCtx.globalAlpha = 0.28;
    const cropY = Math.floor(earthImagery.image.naturalHeight * 0.48);
    const cropH = Math.floor(earthImagery.image.naturalHeight * 0.36);
    povCtx.drawImage(
      earthImagery.image,
      0,
      cropY,
      earthImagery.image.naturalWidth,
      cropH,
      0,
      horizon,
      width,
      height - horizon,
    );
    povCtx.restore();
  }

  povCtx.fillStyle = "rgba(55, 74, 70, 0.55)";
  povCtx.beginPath();
  povCtx.moveTo(0, horizon);
  for (let i = 0; i <= 8; i += 1) {
    const x = (i / 8) * width;
    const y = horizon - Math.sin(i * 1.7) * 28 - 34;
    povCtx.lineTo(x, y);
  }
  povCtx.lineTo(width, horizon);
  povCtx.closePath();
  povCtx.fill();

  povCtx.strokeStyle = "#e6c35c";
  povCtx.lineWidth = 2;
  povCtx.beginPath();
  povCtx.moveTo(0, horizon);
  povCtx.lineTo(width, horizon);
  povCtx.stroke();

  povCtx.fillStyle = "rgba(230,195,92,0.1)";
  povCtx.beginPath();
  povCtx.moveTo(width * 0.42, height);
  povCtx.lineTo(width * 0.49, horizon);
  povCtx.lineTo(width * 0.53, horizon);
  povCtx.lineTo(width * 0.68, height);
  povCtx.closePath();
  povCtx.fill();

  drawReticle(width, height);
  drawPovTelemetry(drone, width, height);
  overlay.innerHTML = "";

  for (const obj of visible) {
    const x = obj.screenX * width;
    const y = obj.screenY * height;
    const radius = obj.type === "ground" ? 9 : 14;
    povCtx.fillStyle = obj.threat === "critical" ? "#ff5d5d" : "#55d6a6";
    povCtx.strokeStyle = "#f2efe5";
    povCtx.lineWidth = 2;
    povCtx.beginPath();
    if (obj.type === "ground") {
      povCtx.rect(x - radius, y - radius / 2, radius * 2, radius);
    } else {
      povCtx.moveTo(x, y - radius);
      povCtx.lineTo(x + radius * 1.4, y + radius);
      povCtx.lineTo(x - radius * 1.4, y + radius);
      povCtx.closePath();
    }
    povCtx.fill();
    povCtx.stroke();

    const label = document.createElement("div");
    label.className = "target-label";
    label.style.left = `${x}px`;
    label.style.top = `${y}px`;
    label.textContent = `${obj.callsign} ${obj.range}m`;
    overlay.appendChild(label);
  }
}

function drawReticle(width, height) {
  povCtx.strokeStyle = "rgba(242, 239, 229, 0.55)";
  povCtx.lineWidth = 1;
  povCtx.beginPath();
  povCtx.moveTo(width / 2 - 42, height / 2);
  povCtx.lineTo(width / 2 + 42, height / 2);
  povCtx.moveTo(width / 2, height / 2 - 42);
  povCtx.lineTo(width / 2, height / 2 + 42);
  povCtx.stroke();
  povCtx.beginPath();
  povCtx.arc(width / 2, height / 2, 52, 0, Math.PI * 2);
  povCtx.stroke();
}

function drawPovTelemetry(drone, width, height) {
  povCtx.fillStyle = "rgba(10, 15, 18, 0.62)";
  povCtx.fillRect(18, 18, 230, 72);
  povCtx.fillStyle = "#f2efe5";
  povCtx.font = "14px Inter, Arial";
  povCtx.fillText(`${drone.callsign} ${drone.command.toUpperCase()}`, 32, 42);
  povCtx.fillText(`HDG ${Math.round((drone.heading + 360) % 360)}  ALT ${Math.round(drone.z)}m`, 32, 66);
  povCtx.fillText(`SPD ${Math.round(drone.speed)}m/s  BAT ${Math.round(drone.battery)}%`, 32, 88);
}

function renderAssets() {
  document.querySelector("#asset-list").innerHTML = allAssets()
    .map((asset) => {
      const hit = bvhQuery(asset).find((item) => item.severity === "critical" && item.distance < item.radius);
      const dotClass = hit ? "critical" : asset.battery < 70 ? "warn" : "";
      const selected = asset.id === selectedId ? "selected" : "";
      return `<button class="asset-row ${selected}" data-asset="${asset.id}">
        <div>
          <strong>${asset.callsign}</strong>
          <div class="asset-meta">${asset.command} · ${Math.round(asset.z)}m · ${Math.round(asset.battery)}%</div>
        </div>
        <span class="asset-dot ${dotClass}"></span>
      </button>`;
    })
    .join("");
  document.querySelectorAll(".asset-row").forEach((row) => {
    row.addEventListener("click", () => {
      selectedId = row.dataset.asset;
      renderFrame();
    });
  });
}

function renderHardware(drone, hits) {
  const status = modeCopy();
  const bvhMs = rayPath === "rtx" ? 1.4 + hits.length * 0.16 : 8.8 + hits.length * 0.7;
  const rows = [
    ["Earth imagery", earthImagery.ready ? "NASA Blue Marble cached" : "waiting for local cache", earthImagery.ready ? "good" : "watch"],
    ["Route geometry", rayPath === "rtx" ? "accelerated locally" : "CPU parity view", rayPath === "rtx" ? "good" : "watch"],
    ["Query", `${hits.length} candidates · ${bvhMs.toFixed(1)} ms`, rayPath === "rtx" ? "good" : "watch"],
    ["Mission cache", `${status.sync} staged events`, "local"],
  ];
  document.querySelector("#hardware-list").innerHTML = rows
    .map(
      ([name, detail, kind]) =>
        `<div class="status-row"><div><strong>${name}</strong><div class="status-detail">${detail}</div></div><span class="status-chip ${kind}">${kind}</span></div>`,
    )
    .join("");
  document.querySelector("#bvh-label").textContent = rayPath === "rtx" ? "accelerated geometry" : "CPU geometry";
  document.querySelector("#bvh-badge").textContent =
    earthImagery.ready ? "Earth imagery cached" : "Earth imagery pending";
  document.querySelector("#map-hud-copy").textContent =
    earthImagery.ready ? "NASA Blue Marble raster in local cache" : "Run scripts/cache_visual_assets.py to cache Earth imagery";
  document.querySelector("#range-label").textContent = `${Math.round(Math.max(0, ...hits.map((hit) => hit.distance)))} m`;
  document.querySelector("#pov-title").textContent = `${drone.callsign} POV`;
}

function renderVision(scores) {
  document.querySelector("#vision-scores").innerHTML = scores
    .map(
      ([label, score]) =>
        `<div class="score-row"><strong>${label}</strong><span>${Math.round(score * 100)}%</span><div class="score-bar"><span style="width:${score * 100}%"></span></div></div>`,
    )
    .join("");
}

function renderAlerts(drone, hits, scores) {
  const alerts = [];
  const critical = hits.find((hit) => hit.severity === "critical" && hit.distance < hit.radius);
  if (critical) {
    alerts.push(["critical", `${drone.callsign} inside ${critical.label}; route correction active`]);
  } else if (scores[0][0] === "restricted volume in POV") {
    alerts.push(["critical", "Restricted volume visible in POV"]);
  }
  alerts.push(["watch", "Offline authority active; Maven packet staged"]);
  if (drone.battery < 70) alerts.push(["watch", `${drone.callsign} battery near return threshold`]);
  if (alerts.length === 0) alerts.push(["watch", "Local BVH pass clear"]);
  document.querySelector("#alert-list").innerHTML = alerts
    .map(([level, text]) => `<div class="alert-row ${level}">${text}</div>`)
    .join("");
}

function renderLog() {
  document.querySelector("#mission-log").innerHTML = missionLog
    .map((entry) => `<div class="log-row">${entry}</div>`)
    .join("");
}

function renderCommandQueue() {
  document.querySelector("#command-queue").innerHTML =
    commandQueue.length === 0
      ? '<div class="log-row">No operator commands issued.</div>'
      : commandQueue
          .map(
            (cmd) =>
              `<div class="log-row">${cmd.id} · ${cmd.callsign} · ${cmd.command.toUpperCase()} · ${cmd.status}</div>`,
          )
          .join("");
}

function updateModeChrome() {
  const status = modeCopy();
  const pill = document.querySelector("#mode-status");
  pill.textContent = "OFFLINE FIELD NODE";
  pill.className = "mode-pill offline";
  document.querySelector("#sync-count").textContent = String(status.sync);
  document.querySelector("#foundry-status").textContent = status.foundry;
}

function renderFrame() {
  const drone = selectedDrone();
  const visible = visibleObjects(drone);
  const hits = bvhQuery(drone);
  const scores = classifyFrame(drone, visible);
  drawSwarmMap();
  drawPov(drone, visible);
  renderAssets();
  renderHardware(drone, hits);
  renderVision(scores);
  renderAlerts(drone, hits, scores);
  renderLog();
  renderCommandQueue();
  updateModeChrome();
  document.querySelector("#clock-label").textContent = `T+${simTime.toFixed(1)}s`;
  document.querySelector("#frame-counter").textContent = simPaused ? "Paused" : "Local replay";
  document.querySelector("#field-condition-label").textContent = scores[0][0];
  document.querySelector("#npu-label").textContent = modeCopy().npu;
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
  const assets = allAssets();
  const current = Math.max(0, assets.findIndex((asset) => asset.id === selectedId));
  const next = (current + offset + assets.length) % assets.length;
  selectedId = assets[next].id;
  pushLog(`POV switched to ${assets[next].callsign}.`);
  renderFrame();
}

document.querySelector("#resume-mission").addEventListener("click", () => issueCommand("resume"));
document.querySelector("#patrol-area").addEventListener("click", () => issueCommand("patrol"));
document.querySelector("#return-home").addEventListener("click", () => issueCommand("return"));
document.querySelector("#hold-position").addEventListener("click", () => issueCommand("hold"));
document.querySelector("#emergency-stop").addEventListener("click", () => issueCommand("abort"));
document.querySelector("#prev-frame").addEventListener("click", () => cycleSelected(-1));
document.querySelector("#next-frame").addEventListener("click", () => cycleSelected(1));
document.querySelector("#toggle-bvh").addEventListener("click", () => {
  rayPath = rayPath === "rtx" ? "cpu" : "rtx";
  pushLog(`BVH path switched to ${rayPath === "rtx" ? "RTX ray cores" : "CPU parity"} locally.`);
});

pushLog("Offline field node started; local graphics and Earth imagery cache active.");
requestAnimationFrame(tick);
