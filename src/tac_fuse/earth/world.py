"""
TAC-FUSE Earth Emulator World Model.

Provides a Google-Earth-style tactical scene emulator with:
- Scenario origin (lat, lon, alt)
- WGS84-ish lat/lon/alt to local ENU conversion
- World extents in meters
- Terrain sample records (elevation, slope, landcover, obstacle id)
- Deterministic time-step state for offline replay
"""

import json
import math
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
import hashlib


@dataclass
class TerrainSample:
    """Single terrain sample at a specific location."""
    elevation: float  # meters above WGS84 ellipsoid
    slope: float      # gradient magnitude (rise/run, unitless)
    landcover: int    # integer code representing landcover type
    obstacle_id: Optional[int] = None  # ID if obstacle present, else None


@dataclass
class WorldState:
    """Deterministic state of the world at a specific time."""
    time: float
    terrain_samples: Dict[Tuple[int, int], TerrainSample] = field(default_factory=dict)
    # Additional dynamic state can be added here (e.g., moving objects)


class World:
    """
    Tactical scene emulator world model.
    
    Loads normalized map fixture when available, otherwise generates
    deterministic procedural terrain.
    """
    
    # Earth parameters (WGS84)
    EARTH_RADIUS = 6378137.0  # meters at equator
    
    # Landcover codes (simple classification)
    LANDCOVER_WATER = 0
    LANDCOVER_GRASS = 1
    LANDCOVER_ROCK = 2
    LANDCOVER_BUILDING = 3
    LANDCOVER_TREE = 4
    
    def __init__(
        self,
        origin_lat: float,
        origin_lon: float,
        origin_alt: float = 0.0,
        fixture_path: Optional[str] = None,
        world_extent_meters: float = 500.0,
        time_start: float = 0.0
    ):
        """
        Initialize the world model.
        
        Args:
            origin_lat: Scenario origin latitude in degrees
            origin_lon: Scenario origin longitude in degrees
            origin_alt: Scenario origin altitude in meters (ellipsoidal)
            fixture_path: Path to normalized map fixture (JSON)
            world_extent_meters: Half-width/height of square world in meters
            time_start: Simulation start time in seconds
        """
        self.origin_lat = origin_lat
        self.origin_lon = origin_lon
        self.origin_alt = origin_alt
        self.world_extent_meters = world_extent_meters
        self.current_time = time_start
        
        # Convert origin to radians for trigonometric functions
        self.origin_lat_rad = math.radians(origin_lat)
        self.origin_lon_rad = math.radians(origin_lon)
        
        # Precompute cosine of origin latitude for efficiency
        self.cos_lat = math.cos(self.origin_lat_rad)
        
        # Initialize terrain samples
        self.terrain_samples: Dict[Tuple[int, int], TerrainSample] = {}
        
        # Load fixture if provided and exists, otherwise generate procedural
        if fixture_path and os.path.exists(fixture_path):
            self._load_fixture(fixture_path)
        else:
            self._generate_procedural_terrain()
    
    def _load_fixture(self, fixture_path: str) -> None:
        """
        Load normalized map fixture from JSON file.
        
        Expected fixture format:
        {
            "extent_meters": 500.0,
            "terrain_samples": [
                {
                    "grid_x": 0,
                    "grid_y": 0,
                    "elevation": 10.5,
                    "slope": 0.1,
                    "landcover": 1,
                    "obstacle_id": null
                },
                ...
            ]
        }
        """
        try:
            with open(fixture_path, 'r') as f:
                data = json.load(f)
            
            # Override extent if specified in fixture
            if "extent_meters" in data:
                self.world_extent_meters = data["extent_meters"]
            
            # Load terrain samples
            for sample_data in data.get("terrain_samples", []):
                grid_x = sample_data["grid_x"]
                grid_y = sample_data["grid_y"]
                sample = TerrainSample(
                    elevation=sample_data["elevation"],
                    slope=sample_data["slope"],
                    landcover=sample_data["landcover"],
                    obstacle_id=sample_data.get("obstacle_id")
                )
                self.terrain_samples[(grid_x, grid_y)] = sample
                
        except (FileNotFoundError, json.JSONDecodeError, KeyError) as e:
            # Fall back to procedural generation on any error
            print(f"Warning: Failed to load fixture {fixture_path}: {e}")
            print("Falling back to procedural terrain generation.")
            self._generate_procedural_terrain()
    
    def _generate_procedural_terrain(self) -> None:
        """
        Generate deterministic procedural terrain based on origin.
        
        Uses hash-based noise for reproducibility without external dependencies.
        """
        # Grid resolution: 10 meters between samples
        grid_spacing = 10.0
        extent_half = self.world_extent_meters
        
        # Calculate grid dimensions
        grid_size = int(2 * extent_half / grid_spacing) + 1
        offset = extent_half  # shift so (-extent, -extent) maps to (0,0)
        
        # Generate deterministic seed based on origin
        seed_string = f"{self.origin_lat:.6f},{self.origin_lon:.6f},{self.origin_alt:.2f}"
        seed_hash = hashlib.md5(seed_string.encode()).hexdigest()
        seed_int = int(seed_hash[:8], 16)  # Use first 8 hex chars as seed
        
        # Generate terrain samples
        for i in range(grid_size):
            for j in range(grid_size):
                # Grid coordinates
                grid_x = i
                grid_y = j
                
                # Convert grid to world coordinates (meters from origin)
                east = (i * grid_spacing) - offset
                north = (j * grid_spacing) - offset
                
                # Generate deterministic elevation using hashed noise
                elevation = self._hash_noise(east, north, seed_int, 0.1, 20.0)
                
                # Calculate slope as magnitude of gradient (finite difference)
                slope = self._calculate_slope(east, north, grid_spacing, seed_int)
                
                # Determine landcover based on elevation and slope
                landcover = self._determine_landcover(elevation, slope)
                
                # Deterministically place obstacles (low probability)
                obstacle_id = None
                if self._hash_noise(east, north, seed_int + 1000, 0.0, 1.0) > 0.95:
                    obstacle_id = hash((east, north, seed_int)) % 10000  # Simple ID
                
                sample = TerrainSample(
                    elevation=elevation,
                    slope=slope,
                    landcover=landcover,
                    obstacle_id=obstacle_id
                )
                self.terrain_samples[(grid_x, grid_y)] = sample
    
    def _hash_noise(
        self, 
        x: float, 
        y: float, 
        seed: int, 
        scale: float = 1.0, 
        amplitude: float = 1.0
    ) -> float:
        """
        Generate deterministic noise value using hash function.
        
        Returns value in range [-amplitude, amplitude].
        """
        # Create a deterministic hash from inputs
        hash_input = f"{seed}:{x:.3f}:{y:.3f}".encode()
        hash_int = int(hashlib.md5(hash_input).hexdigest(), 16)
        # Normalize to [0, 1] then scale to [-amplitude, amplitude]
        normalized = (hash_int % 10000) / 10000.0  # [0, 1]
        return (normalized * 2.0 - 1.0) * amplitude * scale
    
    def _calculate_slope(
        self, 
        east: float, 
        north: float, 
        grid_spacing: float,
        seed: int
    ) -> float:
        """
        Calculate slope magnitude using central differences.
        """
        # Sample points at +/- grid_spacing in each direction
        eps = grid_spacing
        
        z_center = self._hash_noise(east, north, seed, 0.1, 20.0)
        
        z_east = self._hash_noise(east + eps, north, seed, 0.1, 20.0)
        z_west = self._hash_noise(east - eps, north, seed, 0.1, 20.0)
        z_north = self._hash_noise(east, north + eps, seed, 0.1, 20.0)
        z_south = self._hash_noise(east, north - eps, seed, 0.1, 20.0)
        
        # Central differences
        dz_de = (z_east - z_west) / (2.0 * eps)
        dz_dn = (z_north - z_south) / (2.0 * eps)
        
        # Slope magnitude (rise/run)
        slope = math.sqrt(dz_de**2 + dz_dn**2)
        return slope
    
    def _determine_landcover(self, elevation: float, slope: float) -> int:
        """
        Determine landcover type based on elevation and slope.
        """
        # Simple classification rules
        if elevation < -5.0:  # Below water level
            return self.LANDCOVER_WATER
        elif slope > 0.3:  # Steep slope
            return self.LANDCOVER_ROCK
        elif elevation > 10.0 and self._hash_noise(0, 0, 42, 0.0, 1.0) > 0.7:
            # Higher elevation with random chance for trees
            return self.LANDCOVER_TREE
        elif self._hash_noise(0, 0, 43, 0.0, 1.0) > 0.9:
            # Random chance for buildings
            return self.LANDCOVER_BUILDING
        else:
            return self.LANDCOVER_GRASS
    
    def latlonalt_to_enu(
        self, 
        lat: float, 
        lon: float, 
        alt: float
    ) -> Tuple[float, float, float]:
        """
        Convert WGS84 latitude, longitude, altitude to local ENU coordinates.
        
        Uses simple equirectangular projection (accurate for small areas).
        
        Returns:
            Tuple of (east, north, up) in meters relative to origin.
        """
        # Convert to radians
        lat_rad = math.radians(lat)
        lon_rad = math.radians(lon)
        
        # Differences from origin
        d_lat = lat_rad - self.origin_lat_rad
        d_lon = lon_rad - self.origin_lon_rad
        
        # ENU coordinates (approximate for small distances)
        east = self.EARTH_RADIUS * self.cos_lat * d_lon
        north = self.EARTH_RADIUS * d_lat
        up = alt - self.origin_alt
        
        return (east, north, up)
    
    def enu_to_latlonalt(
        self, 
        east: float, 
        north: float, 
        up: float
    ) -> Tuple[float, float, float]:
        """
        Convert local ENU coordinates to WGS84 latitude, longitude, altitude.
        
        Returns:
            Tuple of (latitude, longitude, altitude) in degrees and meters.
        """
        # Reverse of latlonalt_to_enu
        d_lat = north / self.EARTH_RADIUS
        d_lon = east / (self.EARTH_RADIUS * self.cos_lat)
        
        lat_rad = self.origin_lat_rad + d_lat
        lon_rad = self.origin_lon_rad + d_lon
        alt = up + self.origin_alt
        
        lat = math.degrees(lat_rad)
        lon = math.degrees(lon_rad)
        
        return (lat, lon, alt)
    
    def get_terrain_sample(
        self, 
        east: float, 
        north: float
    ) -> Optional[TerrainSample]:
        """
        Get terrain sample at the given ENU coordinates.
        
        Returns nearest grid sample or None if outside world bounds.
        """
        # Check if within world bounds
        if abs(east) > self.world_extent_meters or abs(north) > self.world_extent_meters:
            return None
        
        # Convert to grid coordinates
        grid_spacing = 10.0
        offset = self.world_extent_meters
        
        grid_x = round((east + offset) / grid_spacing)
        grid_y = round((north + offset) / grid_spacing)
        
        # Ensure grid indices are integers
        grid_x = int(grid_x)
        grid_y = int(grid_y)
        
        return self.terrain_samples.get((grid_x, grid_y))
    
    def get_world_extents(self) -> Tuple[float, float, float, float]:
        """
        Get world extents in ENU meters.
        
        Returns:
            Tuple of (min_east, max_east, min_north, max_north).
        """
        return (
            -self.world_extent_meters,
            self.world_extent_meters,
            -self.world_extent_meters,
            self.world_extent_meters
        )
    
    def advance_time(self, dt: float) -> None:
        """
        Advance simulation time by dt seconds.
        
        Args:
            dt: Time step in seconds (can be negative for rewinding).
        """
        self.current_time += dt
        # In a more complex model, we would update dynamic state here
        # For now, time is the only state variable
    
    def get_state(self) -> WorldState:
        """
        Get current deterministic world state.
        
        Returns:
            WorldState object containing time and terrain samples.
        """
        return WorldState(
            time=self.current_time,
            terrain_samples=self.terrain_samples.copy()
        )
    
    def set_state(self, state: WorldState) -> None:
        """
        Set the world to a previous state (for replay).
        
        Args:
            state: WorldState to restore.
        """
        self.current_time = state.time
        self.terrain_samples = state.terrain_samples.copy()


# Convenience function for quick world creation
def create_demo_world() -> World:
    """
    Create a demonstration world centered at a default location.
    
    Returns:
        World instance centered at San Francisco area for demo purposes.
    """
    # Default origin: San Francisco area
    return World(
        origin_lat=37.7749,
        origin_lon=-122.4194,
        origin_alt=10.0,
        world_extent_meters=200.0
    )


if __name__ == "__main__":
    # Simple demo when run directly
    world = create_demo_world()
    print(f"Created world with origin: {world.origin_lat}, {world.origin_lon}, {world.origin_alt}")
    print(f"World extents: {world.get_world_extents()}")
    
    # Test conversion
    test_lat, test_lon, test_alt = 37.7750, -122.4193, 15.0
    east, north, up = world.latlonalt_to_enu(test_lat, test_lon, test_alt)
    print(f"Point ({test_lat}, {test_lon}, {test_alt}) -> ENU ({east:.2f}, {north:.2f}, {up:.2f})")
    
    # Get terrain sample at that point
    sample = world.get_terrain_sample(east, north)
    if sample:
        print(f"Terrain sample: elevation={sample.elevation:.1f}m, slope={sample.slope:.3f}, "
              f"landcover={sample.landcover}, obstacle_id={sample.obstacle_id}")
    else:
        print("Point outside world extents")
