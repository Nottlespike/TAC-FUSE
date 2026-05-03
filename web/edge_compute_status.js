// Default static status. Regenerate on Strix with:
// uv run python scripts/write_edge_compute_status.py --output web/edge_compute_status.js --device NPU --model-dir models/siglip2-field-npu
window.TAC_FUSE_EDGE_COMPUTE = {
  "generated_at": null,
  "host": "Strix",
  "npu": {
    "device": "NPU",
    "model_dir": "models/siglip2-field-npu",
    "model_id": "google/siglip2-base-patch16-224",
    "model_present": false,
    "npu_device_visible": false,
    "openvino_available": false,
    "ready": false,
    "reason": "checked-in fallback; regenerate on Strix for live readiness"
  },
  "pipeline": {
    "device": "NPU",
    "generated_by": "scripts/write_edge_compute_status.py",
    "model_dir": "models/siglip2-field-npu"
  },
  "ray": {
    "accelerated": false,
    "available": true,
    "backend": "validation",
    "reason": "checked-in fallback; validation geometry is active until Strix acceleration is verified"
  },
  "source": "checked_in_fallback",
  "ui": {
    "backend_label": "Validation Geometry",
    "compute_mode": "validation_rt_control",
    "npu_label": "Edge NPU Unverified",
    "route_guard_use_case": "Automatic corridor geometry and local cue classification",
    "stale_after_seconds": 300,
    "summary_label": "Validation RT Control"
  }
};
