# Borrow Miner

**A psychologically satisfying arcade mining game that teaches Rust ownership concepts through gameplay mechanics.**

Built with [Bevy](https://bevyengine.org/) — a data-driven game engine written in Rust.

## Design Philosophy: "Terminal Luxe"

Yacht club aesthetics meets industrial Rust. Navy foundations with amber/gold accents, phosphor glow effects, and monospace typography create a premium-feeling experience that respects the technical nature of what we're teaching.

## Psychological Architecture

| Hook | Implementation | Neuroscience |
|------|----------------|--------------|
| **Immediate Feedback** | Particles spawn within one frame of click | Closes action-perception loop |
| **Variable Reward** | Weighted ore rarity (2% Platinum → 40% Iron) | Dopamine from uncertainty |
| **Progress Visibility** | Combo meter, depth multiplier, score | Completion drive |
| **Mastery Expression** | Ownership lifecycle bonuses | Skill ceiling for replay |
| **Screen Shake** | Rare finds trigger camera shake | Amplifies surprise |

## Rust Ownership → Gameplay Mapping

| Rust Concept | Game Mechanic |
|--------------|---------------|
| Ownership | Ore enters "OWNED" inventory on mine |
| `Drop` trait | "DROP(&mut self)" button returns ore |
| Lifetime `'a` | Visual label on owned section |
| Borrow checker | Can't drop what you don't own |
| Move semantics | Ore removed from owned when dropped |

## Building

### Prerequisites

- Rust 1.75+ (2024 edition)
- System dependencies for Bevy:
  - **Linux**: `libasound2-dev libudev-dev pkg-config`
  - **macOS**: Xcode Command Line Tools
  - **Windows**: Visual Studio Build Tools

### Development Build (Fast Compile)

```bash
cd borrow_miner
cargo run
```

Note: First build downloads and compiles Bevy (~2-5 min). Subsequent builds use dynamic linking for faster iteration.

### Release Build (Optimized)

```bash
cargo build --release
./target/release/borrow_miner
```

### WASM Build (Web Deployment)

```bash
# Install WASM target
rustup target add wasm32-unknown-unknown

# Install wasm-bindgen-cli
cargo install wasm-bindgen-cli

# Build
cargo build --release --target wasm32-unknown-unknown

# Generate bindings
wasm-bindgen --out-dir ./web --target web \
    ./target/wasm32-unknown-unknown/release/borrow_miner.wasm
```

## Project Structure

```
borrow_miner/
├── Cargo.toml          # Dependencies and build config
├── README.md           # This file
└── src/
    └── main.rs         # Complete game (monolithic for prototype)
```

### Future Modular Structure

```
src/
├── main.rs             # Entry point
├── lib.rs              # Public API
├── game/
│   ├── mod.rs          # Game module root
│   ├── components.rs   # ECS components
│   ├── systems.rs      # Game systems
│   └── resources.rs    # Shared resources
├── ui/
│   ├── mod.rs          # UI module root
│   ├── header.rs       # Score/combo/depth
│   └── footer.rs       # Inventory display
└── audio/
    ├── mod.rs          # Audio module
    └── synthesis.rs    # Procedural sound
```

## ECS Architecture

### Components

| Component | Purpose |
|-----------|---------|
| `Particle` | Velocity, lifetime, color for effects |
| `FloatingScore` | Rising score indicators |
| `ScreenShake` | Camera displacement effect |
| `OwnedSlot` | UI slot for owned ore display |
| `ComboMeter` | Individual combo bar segment |

### Resources

| Resource | Purpose |
|----------|---------|
| `GameState` | Score, combo, depth, owned ores, RNG |

### Systems (Update Order)

1. `handle_mining_input` — Process clicks, spawn effects
2. `handle_drop_input` — Process drop button
3. `update_particles` — Physics for particle effects
4. `update_floating_scores` — Animate score popups
5. `update_screen_shake` — Camera displacement
6. `update_combo_decay` — Timer-based combo reduction
7. `update_cooldown` — Mining rate limiting
8. `update_*_display` — UI synchronization

## Controls

| Input | Action |
|-------|--------|
| Left Click (anywhere) | Mine ore |
| Click DROP button | Return ore, gain bonus |

## Configuration Constants

```rust
const COMBO_DECAY_INTERVAL: f32 = 2.0;  // Seconds before combo drops
const MINING_COOLDOWN: f32 = 0.2;        // Click rate limit
const MAX_COMBO: u32 = 10;               // Combo ceiling
const MAX_OWNED: usize = 5;              // Inventory size
```

## Color Palette (Terminal Luxe)

| Name | Hex | Usage |
|------|-----|-------|
| Foundation Navy | `#0a1628` | Background |
| Amber Gold | `#f4a623` | Primary accent, score |
| Phosphor Green | `#4ade80` | Success states |
| Cyan Glow | `#22d3ee` | Depth indicator |
| Slate Dim | `#94a3b8` | Secondary text |

## Roadmap

- [ ] Audio synthesis with `rodio` (procedural mining sounds)
- [ ] Tutorial overlay for first-time players
- [ ] Lifetime visualization mode (ownership chains)
- [ ] Leaderboard with persistence
- [ ] WASM deployment to itch.io

## License

MIT License — NexVigilant LLC

---

*"Empowerment Through Vigilance"*
