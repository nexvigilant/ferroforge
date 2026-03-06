//! Borrow Miner - Rust Native Arcade Game
//!
//! A psychologically satisfying mining game that teaches Rust ownership concepts
//! through gameplay mechanics. Built with Bevy ECS.
//!
//! Design Philosophy: "Terminal Luxe" - yacht club aesthetics meets industrial Rust
//!
//! Psychological Hooks:
//! - Immediate feedback (<50ms response)
//! - Variable reward schedule (ore rarity)
//! - Progress visibility (combo, depth, score)
//! - Mastery expression (ownership chain bonuses)

use bevy::prelude::*;
use bevy::window::{PrimaryWindow, WindowMode};
use bevy::sprite::MaterialMesh2dBundle;
use rand::prelude::*;
use std::collections::VecDeque;

// ============================================
// Constants - Terminal Luxe Color Palette
// ============================================

const FOUNDATION_NAVY: Color = Color::srgb(0.039, 0.086, 0.157);      // #0a1628
const DEEP_NAVY: Color = Color::srgb(0.051, 0.122, 0.235);            // #0d1f3c
const AMBER_GOLD: Color = Color::srgb(0.957, 0.651, 0.137);           // #f4a623
const PHOSPHOR_GREEN: Color = Color::srgb(0.290, 0.851, 0.502);       // #4ade80
const CYAN_GLOW: Color = Color::srgb(0.133, 0.827, 0.933);            // #22d3ee
const SLATE_DIM: Color = Color::srgb(0.580, 0.639, 0.721);            // #94a3b8
const SLATE_DARK: Color = Color::srgb(0.278, 0.333, 0.412);           // #475569

// Ore Colors
const IRON_COLOR: Color = Color::srgb(0.788, 0.635, 0.153);           // #c9a227
const COPPER_COLOR: Color = Color::srgb(0.722, 0.451, 0.200);         // #b87333
const SILVER_COLOR: Color = Color::srgb(0.753, 0.753, 0.753);         // #c0c0c0
const GOLD_COLOR: Color = Color::srgb(1.0, 0.843, 0.0);               // #ffd700
const PLATINUM_COLOR: Color = Color::srgb(0.898, 0.894, 0.886);       // #e5e4e2

// Game Constants
const PARTICLE_COUNT: usize = 8;
const PARTICLE_RARE_COUNT: usize = 16;
const COMBO_DECAY_INTERVAL: f32 = 2.0;
const MINING_COOLDOWN: f32 = 0.2;
const MAX_COMBO: u32 = 10;
const MAX_OWNED: usize = 5;
const MAX_DROPPED: usize = 3;

// ============================================
// Core Types - Ore System
// ============================================

#[derive(Debug, Clone, Copy, PartialEq)]
pub enum OreType {
    Iron,
    Copper,
    Silver,
    Gold,
    Platinum,
}

impl OreType {
    pub fn symbol(&self) -> &'static str {
        match self {
            OreType::Iron => "Fe",
            OreType::Copper => "Cu",
            OreType::Silver => "Ag",
            OreType::Gold => "Au",
            OreType::Platinum => "Pt",
        }
    }

    pub fn color(&self) -> Color {
        match self {
            OreType::Iron => IRON_COLOR,
            OreType::Copper => COPPER_COLOR,
            OreType::Silver => SILVER_COLOR,
            OreType::Gold => GOLD_COLOR,
            OreType::Platinum => PLATINUM_COLOR,
        }
    }

    pub fn base_value(&self) -> u32 {
        match self {
            OreType::Iron => 10,
            OreType::Copper => 25,
            OreType::Silver => 50,
            OreType::Gold => 100,
            OreType::Platinum => 250,
        }
    }

    pub fn rarity(&self) -> f32 {
        match self {
            OreType::Iron => 0.40,
            OreType::Copper => 0.30,
            OreType::Silver => 0.20,
            OreType::Gold => 0.08,
            OreType::Platinum => 0.02,
        }
    }

    pub fn is_rare(&self) -> bool {
        self.rarity() <= 0.1
    }
}

/// Weighted random ore selection - variable reward schedule
pub fn roll_ore(rng: &mut impl Rng) -> OreType {
    let roll: f32 = rng.gen();
    let mut cumulative = 0.0;
    
    for ore in [OreType::Iron, OreType::Copper, OreType::Silver, OreType::Gold, OreType::Platinum] {
        cumulative += ore.rarity();
        if roll <= cumulative {
            return ore;
        }
    }
    OreType::Iron
}

// ============================================
// ECS Components
// ============================================

/// Marker for the main camera
#[derive(Component)]
pub struct MainCamera;

/// Particle effect component
#[derive(Component)]
pub struct Particle {
    pub velocity: Vec2,
    pub life: f32,
    pub color: Color,
}

/// Floating score indicator
#[derive(Component)]
pub struct FloatingScore {
    pub life: f32,
    pub velocity: Vec2,
}

/// Owned ore in inventory
#[derive(Component)]
pub struct OwnedOre {
    pub ore_type: OreType,
    pub slot: usize,
}

/// Dropped ore indicator
#[derive(Component)]
pub struct DroppedOre {
    pub slot: usize,
}

/// Screen shake effect
#[derive(Component)]
pub struct ScreenShake {
    pub intensity: f32,
    pub duration: f32,
}

/// UI components
#[derive(Component)]
pub struct ScoreText;

#[derive(Component)]
pub struct ComboMeter {
    pub index: usize,
}

#[derive(Component)]
pub struct DepthText;

#[derive(Component)]
pub struct MiningIndicator;

#[derive(Component)]
pub struct DropButton;

#[derive(Component)]
pub struct OwnedSlot {
    pub index: usize,
}

#[derive(Component)]
pub struct DroppedSlot {
    pub index: usize,
}

// ============================================
// Resources - Game State
// ============================================

#[derive(Resource)]
pub struct GameState {
    pub score: u64,
    pub combo: u32,
    pub depth: f32,
    pub owned_ores: VecDeque<OreType>,
    pub dropped_count: usize,
    pub mining_cooldown: f32,
    pub combo_timer: f32,
    pub rng: rand_chacha::ChaCha8Rng,
}

impl Default for GameState {
    fn default() -> Self {
        Self {
            score: 0,
            combo: 0,
            depth: 1.0,
            owned_ores: VecDeque::new(),
            dropped_count: 0,
            mining_cooldown: 0.0,
            combo_timer: COMBO_DECAY_INTERVAL,
            rng: rand_chacha::ChaCha8Rng::from_entropy(),
        }
    }
}

impl GameState {
    /// Calculate score with multipliers
    pub fn calculate_score(&self, ore: OreType) -> u64 {
        let multiplier = 1.0 + (self.combo as f32 * 0.1);
        (ore.base_value() as f32 * multiplier * self.depth) as u64
    }

    /// Drop bonus for proper lifecycle management
    pub fn drop_bonus(&self) -> u64 {
        (25.0 * self.depth) as u64
    }
}

// ============================================
// Plugin Organization
// ============================================

pub struct BorrowMinerPlugin;

impl Plugin for BorrowMinerPlugin {
    fn build(&self, app: &mut App) {
        app
            .init_resource::<GameState>()
            .add_systems(Startup, (
                setup_camera,
                setup_background,
                setup_ui,
            ))
            .add_systems(Update, (
                handle_mining_input,
                handle_drop_input,
                update_particles,
                update_floating_scores,
                update_screen_shake,
                update_combo_decay,
                update_cooldown,
                update_score_display,
                update_combo_display,
                update_depth_display,
                update_owned_display,
                update_dropped_display,
                animate_mining_indicator,
            ));
    }
}

// ============================================
// Startup Systems
// ============================================

fn setup_camera(mut commands: Commands) {
    commands.spawn((
        Camera2dBundle::default(),
        MainCamera,
    ));
}

fn setup_background(mut commands: Commands) {
    // Main background
    commands.spawn(SpriteBundle {
        sprite: Sprite {
            color: FOUNDATION_NAVY,
            custom_size: Some(Vec2::new(2000.0, 2000.0)),
            ..default()
        },
        transform: Transform::from_xyz(0.0, 0.0, -10.0),
        ..default()
    });

    // Grid lines (subtle)
    for i in -25..=25 {
        let pos = i as f32 * 40.0;
        // Vertical
        commands.spawn(SpriteBundle {
            sprite: Sprite {
                color: Color::srgba(0.957, 0.651, 0.137, 0.03),
                custom_size: Some(Vec2::new(1.0, 2000.0)),
                ..default()
            },
            transform: Transform::from_xyz(pos, 0.0, -9.0),
            ..default()
        });
        // Horizontal
        commands.spawn(SpriteBundle {
            sprite: Sprite {
                color: Color::srgba(0.957, 0.651, 0.137, 0.03),
                custom_size: Some(Vec2::new(2000.0, 1.0)),
                ..default()
            },
            transform: Transform::from_xyz(0.0, pos, -9.0),
            ..default()
        });
    }

    // Depth glow at bottom
    commands.spawn(SpriteBundle {
        sprite: Sprite {
            color: Color::srgba(0.957, 0.651, 0.137, 0.15),
            custom_size: Some(Vec2::new(800.0, 200.0)),
            ..default()
        },
        transform: Transform::from_xyz(0.0, -300.0, -8.0),
        ..default()
    });
}

fn setup_ui(mut commands: Commands) {
    // Root UI container
    commands.spawn(NodeBundle {
        style: Style {
            width: Val::Percent(100.0),
            height: Val::Percent(100.0),
            flex_direction: FlexDirection::Column,
            justify_content: JustifyContent::SpaceBetween,
            ..default()
        },
        ..default()
    }).with_children(|parent| {
        // Header
        spawn_header(parent);
        
        // Center area (mining zone)
        spawn_mining_zone(parent);
        
        // Footer
        spawn_footer(parent);
    });
}

fn spawn_header(parent: &mut ChildBuilder) {
    parent.spawn(NodeBundle {
        style: Style {
            width: Val::Percent(100.0),
            height: Val::Px(100.0),
            padding: UiRect::all(Val::Px(20.0)),
            justify_content: JustifyContent::SpaceBetween,
            align_items: AlignItems::Center,
            ..default()
        },
        background_color: Color::srgba(0.039, 0.086, 0.157, 0.9).into(),
        ..default()
    }).with_children(|header| {
        // Left: Title + Score
        header.spawn(NodeBundle {
            style: Style {
                flex_direction: FlexDirection::Column,
                ..default()
            },
            ..default()
        }).with_children(|left| {
            // Title
            left.spawn(TextBundle::from_section(
                "BORROW::MINER",
                TextStyle {
                    font_size: 14.0,
                    color: AMBER_GOLD,
                    ..default()
                },
            ));
            // Score
            left.spawn((
                TextBundle::from_section(
                    "0",
                    TextStyle {
                        font_size: 48.0,
                        color: AMBER_GOLD,
                        ..default()
                    },
                ),
                ScoreText,
            ));
        });

        // Right: Combo + Depth
        header.spawn(NodeBundle {
            style: Style {
                column_gap: Val::Px(40.0),
                align_items: AlignItems::Center,
                ..default()
            },
            ..default()
        }).with_children(|right| {
            // Combo meter
            spawn_combo_meter(right);
            // Depth indicator
            spawn_depth_indicator(right);
        });
    });
}

fn spawn_combo_meter(parent: &mut ChildBuilder) {
    parent.spawn(NodeBundle {
        style: Style {
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::Center,
            ..default()
        },
        ..default()
    }).with_children(|combo| {
        combo.spawn(TextBundle::from_section(
            "COMBO",
            TextStyle {
                font_size: 10.0,
                color: SLATE_DIM,
                ..default()
            },
        ));
        combo.spawn(NodeBundle {
            style: Style {
                column_gap: Val::Px(3.0),
                margin: UiRect::top(Val::Px(8.0)),
                ..default()
            },
            ..default()
        }).with_children(|meter| {
            for i in 0..MAX_COMBO as usize {
                meter.spawn((
                    NodeBundle {
                        style: Style {
                            width: Val::Px(8.0),
                            height: Val::Px(24.0),
                            ..default()
                        },
                        background_color: SLATE_DARK.into(),
                        ..default()
                    },
                    ComboMeter { index: i },
                ));
            }
        });
    });
}

fn spawn_depth_indicator(parent: &mut ChildBuilder) {
    parent.spawn(NodeBundle {
        style: Style {
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::Center,
            ..default()
        },
        ..default()
    }).with_children(|depth| {
        depth.spawn(TextBundle::from_section(
            "DEPTH",
            TextStyle {
                font_size: 10.0,
                color: SLATE_DIM,
                ..default()
            },
        ));
        depth.spawn((
            TextBundle::from_section(
                "1.0x",
                TextStyle {
                    font_size: 24.0,
                    color: CYAN_GLOW,
                    ..default()
                },
            ),
            DepthText,
        ));
    });
}

fn spawn_mining_zone(parent: &mut ChildBuilder) {
    parent.spawn(NodeBundle {
        style: Style {
            flex_grow: 1.0,
            justify_content: JustifyContent::Center,
            align_items: AlignItems::Center,
            ..default()
        },
        ..default()
    }).with_children(|zone| {
        // Mining indicator circle
        zone.spawn((
            NodeBundle {
                style: Style {
                    width: Val::Px(120.0),
                    height: Val::Px(120.0),
                    justify_content: JustifyContent::Center,
                    align_items: AlignItems::Center,
                    border: UiRect::all(Val::Px(2.0)),
                    ..default()
                },
                border_color: Color::srgba(0.957, 0.651, 0.137, 0.3).into(),
                border_radius: BorderRadius::all(Val::Percent(50.0)),
                ..default()
            },
            MiningIndicator,
        )).with_children(|indicator| {
            indicator.spawn(TextBundle::from_section(
                "CLICK TO MINE",
                TextStyle {
                    font_size: 12.0,
                    color: Color::srgba(0.957, 0.651, 0.137, 0.6),
                    ..default()
                },
            ));
        });
    });
}

fn spawn_footer(parent: &mut ChildBuilder) {
    parent.spawn(NodeBundle {
        style: Style {
            width: Val::Percent(100.0),
            height: Val::Px(100.0),
            padding: UiRect::all(Val::Px(20.0)),
            justify_content: JustifyContent::SpaceBetween,
            align_items: AlignItems::Center,
            ..default()
        },
        background_color: Color::srgba(0.039, 0.086, 0.157, 0.95).into(),
        ..default()
    }).with_children(|footer| {
        // Owned ores
        spawn_owned_section(footer);
        
        // Drop button
        spawn_drop_button(footer);
        
        // Dropped section
        spawn_dropped_section(footer);
    });
}

fn spawn_owned_section(parent: &mut ChildBuilder) {
    parent.spawn(NodeBundle {
        style: Style {
            flex_direction: FlexDirection::Column,
            ..default()
        },
        ..default()
    }).with_children(|section| {
        section.spawn(TextBundle::from_section(
            "OWNED <'a>",
            TextStyle {
                font_size: 10.0,
                color: SLATE_DIM,
                ..default()
            },
        ));
        section.spawn(NodeBundle {
            style: Style {
                column_gap: Val::Px(8.0),
                margin: UiRect::top(Val::Px(8.0)),
                ..default()
            },
            ..default()
        }).with_children(|slots| {
            for i in 0..MAX_OWNED {
                slots.spawn((
                    NodeBundle {
                        style: Style {
                            width: Val::Px(40.0),
                            height: Val::Px(40.0),
                            justify_content: JustifyContent::Center,
                            align_items: AlignItems::Center,
                            border: UiRect::all(Val::Px(2.0)),
                            ..default()
                        },
                        border_color: SLATE_DARK.into(),
                        border_radius: BorderRadius::all(Val::Px(6.0)),
                        background_color: Color::NONE.into(),
                        ..default()
                    },
                    OwnedSlot { index: i },
                )).with_children(|slot| {
                    slot.spawn(TextBundle::from_section(
                        "",
                        TextStyle {
                            font_size: 16.0,
                            color: Color::WHITE,
                            ..default()
                        },
                    ));
                });
            }
        });
    });
}

fn spawn_drop_button(parent: &mut ChildBuilder) {
    parent.spawn((
        ButtonBundle {
            style: Style {
                padding: UiRect::axes(Val::Px(32.0), Val::Px(12.0)),
                justify_content: JustifyContent::Center,
                align_items: AlignItems::Center,
                border: UiRect::all(Val::Px(2.0)),
                ..default()
            },
            border_color: SLATE_DARK.into(),
            border_radius: BorderRadius::all(Val::Px(8.0)),
            background_color: Color::srgba(0.278, 0.333, 0.412, 0.3).into(),
            ..default()
        },
        DropButton,
    )).with_children(|button| {
        button.spawn(TextBundle::from_section(
            "DROP(&mut self) → +25",
            TextStyle {
                font_size: 14.0,
                color: SLATE_DIM,
                ..default()
            },
        ));
    });
}

fn spawn_dropped_section(parent: &mut ChildBuilder) {
    parent.spawn(NodeBundle {
        style: Style {
            flex_direction: FlexDirection::Column,
            align_items: AlignItems::FlexEnd,
            ..default()
        },
        ..default()
    }).with_children(|section| {
        section.spawn(TextBundle::from_section(
            "DROPPED",
            TextStyle {
                font_size: 10.0,
                color: SLATE_DIM,
                ..default()
            },
        ));
        section.spawn(NodeBundle {
            style: Style {
                column_gap: Val::Px(8.0),
                margin: UiRect::top(Val::Px(8.0)),
                ..default()
            },
            ..default()
        }).with_children(|slots| {
            for i in 0..MAX_DROPPED {
                slots.spawn((
                    NodeBundle {
                        style: Style {
                            width: Val::Px(40.0),
                            height: Val::Px(40.0),
                            justify_content: JustifyContent::Center,
                            align_items: AlignItems::Center,
                            border: UiRect::all(Val::Px(2.0)),
                            ..default()
                        },
                        border_color: SLATE_DARK.into(),
                        border_radius: BorderRadius::all(Val::Px(6.0)),
                        background_color: Color::NONE.into(),
                        ..default()
                    },
                    DroppedSlot { index: i },
                )).with_children(|slot| {
                    slot.spawn(TextBundle::from_section(
                        "",
                        TextStyle {
                            font_size: 14.0,
                            color: PHOSPHOR_GREEN,
                            ..default()
                        },
                    ));
                });
            }
        });
    });
}

// ============================================
// Update Systems - Core Gameplay
// ============================================

fn handle_mining_input(
    mut commands: Commands,
    mouse_button: Res<ButtonInput<MouseButton>>,
    window_query: Query<&Window, With<PrimaryWindow>>,
    camera_query: Query<(&Camera, &GlobalTransform), With<MainCamera>>,
    mut game_state: ResMut<GameState>,
    mut meshes: ResMut<Assets<Mesh>>,
    mut materials: ResMut<Assets<ColorMaterial>>,
) {
    if game_state.mining_cooldown > 0.0 {
        return;
    }

    if !mouse_button.just_pressed(MouseButton::Left) {
        return;
    }

    let window = window_query.single();
    let (camera, camera_transform) = camera_query.single();

    let Some(cursor_pos) = window.cursor_position() else {
        return;
    };

    let Some(world_pos) = camera.viewport_to_world_2d(camera_transform, cursor_pos) else {
        return;
    };

    // Roll for ore (variable reward)
    let ore = roll_ore(&mut game_state.rng);
    let score_gained = game_state.calculate_score(ore);

    // Update game state
    game_state.score += score_gained;
    game_state.combo = (game_state.combo + 1).min(MAX_COMBO);
    game_state.combo_timer = COMBO_DECAY_INTERVAL;
    game_state.mining_cooldown = MINING_COOLDOWN;

    // Add to owned inventory
    if game_state.owned_ores.len() >= MAX_OWNED {
        game_state.owned_ores.pop_front();
    }
    game_state.owned_ores.push_back(ore);

    // Spawn particles
    let particle_count = if ore.is_rare() { PARTICLE_RARE_COUNT } else { PARTICLE_COUNT };
    spawn_particles(&mut commands, world_pos, ore.color(), particle_count, &mut meshes, &mut materials);

    // Spawn floating score
    spawn_floating_score(&mut commands, world_pos, score_gained, ore.color());

    // Screen shake for rare finds
    if ore.is_rare() {
        commands.spawn(ScreenShake {
            intensity: 4.0,
            duration: 0.15,
        });
    }
}

fn handle_drop_input(
    mut interaction_query: Query<
        (&Interaction, &mut BackgroundColor, &mut BorderColor),
        (Changed<Interaction>, With<DropButton>),
    >,
    mut game_state: ResMut<GameState>,
    mut commands: Commands,
) {
    for (interaction, mut bg_color, mut border_color) in &mut interaction_query {
        let has_ores = !game_state.owned_ores.is_empty();
        
        match *interaction {
            Interaction::Pressed if has_ores => {
                // Drop the most recent ore
                if game_state.owned_ores.pop_back().is_some() {
                    let bonus = game_state.drop_bonus();
                    game_state.score += bonus;
                    game_state.depth = (game_state.depth + 0.1).min(10.0);
                    game_state.dropped_count = (game_state.dropped_count + 1).min(MAX_DROPPED);

                    // Visual feedback
                    spawn_floating_score(&mut commands, Vec2::new(0.0, -200.0), bonus, PHOSPHOR_GREEN);
                }
            }
            Interaction::Hovered if has_ores => {
                *bg_color = Color::srgba(0.086, 0.325, 0.204, 1.0).into();
                *border_color = PHOSPHOR_GREEN.into();
            }
            _ => {
                if has_ores {
                    *bg_color = Color::srgba(0.086, 0.325, 0.204, 0.5).into();
                    *border_color = PHOSPHOR_GREEN.into();
                } else {
                    *bg_color = Color::srgba(0.278, 0.333, 0.412, 0.3).into();
                    *border_color = SLATE_DARK.into();
                }
            }
        }
    }
}

// ============================================
// Update Systems - Visual Effects
// ============================================

fn spawn_particles(
    commands: &mut Commands,
    position: Vec2,
    color: Color,
    count: usize,
    meshes: &mut Assets<Mesh>,
    materials: &mut Assets<ColorMaterial>,
) {
    let mesh = meshes.add(Circle::new(3.0));
    
    for i in 0..count {
        let angle = (std::f32::consts::TAU * i as f32 / count as f32) + rand::random::<f32>() * 0.5;
        let speed = 100.0 + rand::random::<f32>() * 150.0;
        let velocity = Vec2::new(angle.cos(), angle.sin()) * speed;

        let material = materials.add(ColorMaterial::from(color));

        commands.spawn((
            MaterialMesh2dBundle {
                mesh: mesh.clone().into(),
                material,
                transform: Transform::from_xyz(position.x, position.y, 10.0),
                ..default()
            },
            Particle {
                velocity,
                life: 1.0,
                color,
            },
        ));
    }
}

fn update_particles(
    mut commands: Commands,
    time: Res<Time>,
    mut query: Query<(Entity, &mut Particle, &mut Transform)>,
) {
    let dt = time.delta_seconds();

    for (entity, mut particle, mut transform) in &mut query {
        // Physics
        particle.velocity.y -= 200.0 * dt; // Gravity
        particle.velocity *= 0.98; // Drag
        particle.life -= dt * 1.5;

        transform.translation.x += particle.velocity.x * dt;
        transform.translation.y += particle.velocity.y * dt;
        transform.scale = Vec3::splat(particle.life.max(0.0));

        if particle.life <= 0.0 {
            commands.entity(entity).despawn();
        }
    }
}

fn spawn_floating_score(commands: &mut Commands, position: Vec2, score: u64, color: Color) {
    commands.spawn((
        Text2dBundle {
            text: Text::from_section(
                format!("+{}", score),
                TextStyle {
                    font_size: 24.0,
                    color,
                    ..default()
                },
            ),
            transform: Transform::from_xyz(position.x, position.y + 20.0, 20.0),
            ..default()
        },
        FloatingScore {
            life: 1.0,
            velocity: Vec2::new(0.0, 60.0),
        },
    ));
}

fn update_floating_scores(
    mut commands: Commands,
    time: Res<Time>,
    mut query: Query<(Entity, &mut FloatingScore, &mut Transform, &mut Text)>,
) {
    let dt = time.delta_seconds();

    for (entity, mut score, mut transform, mut text) in &mut query {
        score.life -= dt;
        transform.translation.y += score.velocity.y * dt;

        // Fade out
        if let Some(section) = text.sections.first_mut() {
            section.style.color = section.style.color.with_alpha(score.life.max(0.0));
        }

        if score.life <= 0.0 {
            commands.entity(entity).despawn();
        }
    }
}

fn update_screen_shake(
    mut commands: Commands,
    time: Res<Time>,
    mut camera_query: Query<&mut Transform, With<MainCamera>>,
    mut shake_query: Query<(Entity, &mut ScreenShake)>,
) {
    let mut total_offset = Vec2::ZERO;

    for (entity, mut shake) in &mut shake_query {
        shake.duration -= time.delta_seconds();
        
        if shake.duration > 0.0 {
            let offset = Vec2::new(
                (rand::random::<f32>() - 0.5) * shake.intensity,
                (rand::random::<f32>() - 0.5) * shake.intensity,
            );
            total_offset += offset;
        } else {
            commands.entity(entity).despawn();
        }
    }

    if let Ok(mut camera_transform) = camera_query.get_single_mut() {
        camera_transform.translation.x = total_offset.x;
        camera_transform.translation.y = total_offset.y;
    }
}

// ============================================
// Update Systems - Game State
// ============================================

fn update_combo_decay(
    time: Res<Time>,
    mut game_state: ResMut<GameState>,
) {
    game_state.combo_timer -= time.delta_seconds();
    
    if game_state.combo_timer <= 0.0 && game_state.combo > 0 {
        game_state.combo -= 1;
        game_state.combo_timer = COMBO_DECAY_INTERVAL;
    }
}

fn update_cooldown(
    time: Res<Time>,
    mut game_state: ResMut<GameState>,
) {
    if game_state.mining_cooldown > 0.0 {
        game_state.mining_cooldown -= time.delta_seconds();
    }
}

// ============================================
// Update Systems - UI Display
// ============================================

fn update_score_display(
    game_state: Res<GameState>,
    mut query: Query<&mut Text, With<ScoreText>>,
) {
    if game_state.is_changed() {
        for mut text in &mut query {
            if let Some(section) = text.sections.first_mut() {
                section.value = format!("{}", game_state.score);
            }
        }
    }
}

fn update_combo_display(
    game_state: Res<GameState>,
    mut query: Query<(&ComboMeter, &mut BackgroundColor)>,
) {
    if game_state.is_changed() {
        for (meter, mut bg_color) in &mut query {
            if meter.index < game_state.combo as usize {
                *bg_color = AMBER_GOLD.into();
            } else {
                *bg_color = SLATE_DARK.into();
            }
        }
    }
}

fn update_depth_display(
    game_state: Res<GameState>,
    mut query: Query<&mut Text, With<DepthText>>,
) {
    if game_state.is_changed() {
        for mut text in &mut query {
            if let Some(section) = text.sections.first_mut() {
                section.value = format!("{:.1}x", game_state.depth);
            }
        }
    }
}

fn update_owned_display(
    game_state: Res<GameState>,
    mut slot_query: Query<(&OwnedSlot, &mut BackgroundColor, &mut BorderColor, &Children)>,
    mut text_query: Query<&mut Text>,
) {
    if game_state.is_changed() {
        for (slot, mut bg_color, mut border_color, children) in &mut slot_query {
            if let Some(ore) = game_state.owned_ores.get(slot.index) {
                let ore_color = ore.color();
                *bg_color = Color::srgba(
                    ore_color.to_srgba().red * 0.2,
                    ore_color.to_srgba().green * 0.2,
                    ore_color.to_srgba().blue * 0.2,
                    0.3
                ).into();
                *border_color = ore_color.into();
                
                for &child in children.iter() {
                    if let Ok(mut text) = text_query.get_mut(child) {
                        if let Some(section) = text.sections.first_mut() {
                            section.value = ore.symbol().to_string();
                            section.style.color = ore_color;
                        }
                    }
                }
            } else {
                *bg_color = Color::NONE.into();
                *border_color = SLATE_DARK.into();
                
                for &child in children.iter() {
                    if let Ok(mut text) = text_query.get_mut(child) {
                        if let Some(section) = text.sections.first_mut() {
                            section.value = String::new();
                        }
                    }
                }
            }
        }
    }
}

fn update_dropped_display(
    game_state: Res<GameState>,
    mut slot_query: Query<(&DroppedSlot, &mut BackgroundColor, &mut BorderColor, &Children)>,
    mut text_query: Query<&mut Text>,
) {
    if game_state.is_changed() {
        for (slot, mut bg_color, mut border_color, children) in &mut slot_query {
            if slot.index < game_state.dropped_count {
                *bg_color = Color::srgba(0.133, 0.773, 0.369, 0.1).into();
                *border_color = Color::srgba(0.133, 0.773, 0.369, 0.4).into();
                
                for &child in children.iter() {
                    if let Ok(mut text) = text_query.get_mut(child) {
                        if let Some(section) = text.sections.first_mut() {
                            section.value = "✓".to_string();
                        }
                    }
                }
            } else {
                *bg_color = Color::NONE.into();
                *border_color = SLATE_DARK.into();
                
                for &child in children.iter() {
                    if let Ok(mut text) = text_query.get_mut(child) {
                        if let Some(section) = text.sections.first_mut() {
                            section.value = String::new();
                        }
                    }
                }
            }
        }
    }
}

fn animate_mining_indicator(
    time: Res<Time>,
    mut query: Query<&mut BorderColor, With<MiningIndicator>>,
) {
    let pulse = (time.elapsed_seconds() * 2.0).sin() * 0.3 + 0.5;
    
    for mut border_color in &mut query {
        *border_color = Color::srgba(0.957, 0.651, 0.137, pulse * 0.3).into();
    }
}

// ============================================
// Main Entry Point
// ============================================

fn main() {
    App::new()
        .add_plugins(DefaultPlugins.set(WindowPlugin {
            primary_window: Some(Window {
                title: "Borrow Miner - Rust Ownership Arcade".to_string(),
                resolution: (1280.0, 720.0).into(),
                present_mode: bevy::window::PresentMode::AutoVsync,
                ..default()
            }),
            ..default()
        }))
        .insert_resource(ClearColor(FOUNDATION_NAVY))
        .add_plugins(BorrowMinerPlugin)
        .run();
}
