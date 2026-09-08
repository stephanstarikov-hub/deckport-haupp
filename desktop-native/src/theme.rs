//! DeckPort's native visual language. No image downloads or extra UI dependencies.
use eframe::egui::{self, Align2, Color32, FontId, Pos2, Rect, Response, Sense, Stroke, Vec2};
use std::f32::consts::{PI, TAU};

pub const BACKGROUND: Color32 = Color32::from_rgb(7, 17, 24);
pub const SIDEBAR: Color32 = Color32::from_rgb(8, 20, 28);
pub const SURFACE: Color32 = Color32::from_rgb(12, 27, 36);
pub const RAISED: Color32 = Color32::from_rgb(18, 37, 47);
pub const BORDER: Color32 = Color32::from_rgb(30, 51, 62);
pub const GREEN: Color32 = Color32::from_rgb(81, 224, 149);
pub const GREEN_DARK: Color32 = Color32::from_rgb(13, 44, 36);
pub const TEXT: Color32 = Color32::from_rgb(233, 242, 246);
pub const MUTED: Color32 = Color32::from_rgb(153, 173, 186);
pub const DIM: Color32 = Color32::from_rgb(115, 137, 152);
pub const AMBER: Color32 = Color32::from_rgb(236, 191, 105);
pub const RED: Color32 = Color32::from_rgb(245, 132, 146);

#[derive(Clone, Copy)]
pub enum Icon {
    Shield,
    Home,
    Servers,
    Link,
    Settings,
    Power,
    Lock,
    Refresh,
    Chevron,
    Star,
    Globe,
    Clock,
    Activity,
}

pub fn apply(ctx: &egui::Context) {
    ctx.set_theme(egui::Theme::Dark);
    let mut style = (*ctx.global_style()).clone();
    style
        .text_styles
        .insert(egui::TextStyle::Body, FontId::proportional(16.0));
    style
        .text_styles
        .insert(egui::TextStyle::Button, FontId::proportional(15.0));
    style
        .text_styles
        .insert(egui::TextStyle::Small, FontId::proportional(13.0));
    style
        .text_styles
        .insert(egui::TextStyle::Heading, FontId::proportional(27.0));
    style.spacing.item_spacing = egui::vec2(10.0, 8.0);
    style.spacing.button_padding = egui::vec2(14.0, 10.0);
    style.spacing.interact_size.y = 38.0;
    style.visuals = egui::Visuals::dark();
    let visuals = &mut style.visuals;
    visuals.override_text_color = Some(TEXT);
    visuals.panel_fill = BACKGROUND;
    visuals.window_fill = SURFACE;
    visuals.faint_bg_color = SURFACE;
    visuals.extreme_bg_color = BACKGROUND;
    visuals.window_stroke = Stroke::new(1.0, BORDER);
    visuals.window_corner_radius = 16.into();
    visuals.selection.bg_fill = GREEN_DARK;
    visuals.selection.stroke = Stroke::new(1.0, GREEN);
    for widget in [
        &mut visuals.widgets.inactive,
        &mut visuals.widgets.noninteractive,
    ] {
        widget.bg_fill = SURFACE;
        widget.weak_bg_fill = SURFACE;
        widget.bg_stroke = Stroke::new(1.0, BORDER);
        widget.fg_stroke = Stroke::new(1.5, TEXT);
        widget.corner_radius = 10.into();
    }
    visuals.widgets.hovered.bg_fill = RAISED;
    visuals.widgets.hovered.weak_bg_fill = RAISED;
    visuals.widgets.hovered.bg_stroke = Stroke::new(1.0, DIM);
    visuals.widgets.hovered.fg_stroke = Stroke::new(1.5, TEXT);
    visuals.widgets.hovered.corner_radius = 10.into();
    visuals.widgets.active.bg_fill = GREEN_DARK;
    visuals.widgets.active.weak_bg_fill = GREEN_DARK;
    visuals.widgets.active.bg_stroke = Stroke::new(1.0, GREEN);
    visuals.widgets.active.fg_stroke = Stroke::new(1.5, GREEN);
    visuals.widgets.active.corner_radius = 10.into();
    ctx.set_global_style(style);
}

pub fn card() -> egui::Frame {
    egui::Frame::new()
        .fill(SURFACE)
        .stroke(Stroke::new(1.0, BORDER))
        .corner_radius(16)
        .inner_margin(18)
}

pub fn heading(ui: &mut egui::Ui, title: &str, subtitle: &str) {
    ui.heading(egui::RichText::new(title).strong());
    if !subtitle.is_empty() {
        ui.label(egui::RichText::new(subtitle).color(MUTED));
    }
    ui.add_space(18.0);
}

pub fn section(ui: &mut egui::Ui, title: &str) {
    ui.label(egui::RichText::new(title).size(17.0).strong());
    ui.add_space(5.0);
}

pub fn primary(label: &str) -> egui::Button<'_> {
    egui::Button::new(egui::RichText::new(label).strong().color(BACKGROUND))
        .fill(GREEN)
        .stroke(Stroke::NONE)
}

/// Uses egui's focusable Button, so keyboard activation matches pointer activation.
pub fn nav(ui: &mut egui::Ui, icon: Icon, label: &str, selected: bool) -> Response {
    let response = ui.add_sized(
        [ui.available_width(), 50.0],
        egui::Button::new("")
            .fill(if selected {
                RAISED
            } else {
                Color32::TRANSPARENT
            })
            .stroke(Stroke::NONE)
            .corner_radius(10),
    );
    response.widget_info(|| {
        egui::WidgetInfo::selected(
            egui::WidgetType::SelectableLabel,
            ui.is_enabled(),
            selected,
            label,
        )
    });
    let rect = response.rect;
    if selected {
        ui.painter().rect_filled(
            Rect::from_min_size(rect.min + egui::vec2(0.0, 8.0), egui::vec2(3.0, 34.0)),
            2,
            GREEN,
        );
    }
    paint_icon(
        ui.painter(),
        icon,
        egui::pos2(rect.left() + 27.0, rect.center().y),
        22.0,
        if selected { GREEN } else { MUTED },
    );
    text(
        ui.painter(),
        egui::pos2(rect.left() + 55.0, rect.center().y),
        label,
        16.0,
        if selected { TEXT } else { MUTED },
        rect.right() - 12.0,
    );
    response
}

pub fn action(ui: &mut egui::Ui, icon: Icon, label: &str) -> Response {
    let response = ui.add_sized([ui.available_width(), 44.0], egui::Button::new(""));
    response.widget_info(|| {
        egui::WidgetInfo::labeled(egui::WidgetType::Button, ui.is_enabled(), label)
    });
    let rect = response.rect;
    paint_icon(
        ui.painter(),
        icon,
        egui::pos2(rect.left() + 23.0, rect.center().y),
        18.0,
        MUTED,
    );
    text(
        ui.painter(),
        egui::pos2(rect.left() + 45.0, rect.center().y),
        label,
        15.0,
        TEXT,
        rect.right() - 30.0,
    );
    paint_icon(
        ui.painter(),
        Icon::Chevron,
        egui::pos2(rect.right() - 18.0, rect.center().y),
        14.0,
        MUTED,
    );
    response
}

pub fn icon_button(ui: &mut egui::Ui, icon: Icon, label: &str, active: bool) -> Response {
    let response = ui.add_sized(
        [38.0, 38.0],
        egui::Button::new("")
            .fill(Color32::TRANSPARENT)
            .stroke(Stroke::NONE),
    );
    response.widget_info(|| {
        egui::WidgetInfo::labeled(egui::WidgetType::Button, ui.is_enabled(), label)
    });
    paint_icon(
        ui.painter(),
        icon,
        response.rect.center(),
        19.0,
        if active { GREEN } else { MUTED },
    );
    response.on_hover_text(label)
}

pub fn switch(ui: &mut egui::Ui, label: &str, value: &mut bool) -> Response {
    let mut response = ui.add_sized(
        [46.0, 32.0],
        egui::Button::new("")
            .fill(Color32::TRANSPARENT)
            .stroke(Stroke::NONE),
    );
    if response.clicked() {
        *value = !*value;
        response.mark_changed();
    }
    response.widget_info(|| {
        egui::WidgetInfo::selected(egui::WidgetType::Checkbox, ui.is_enabled(), *value, label)
    });
    let rect = Rect::from_center_size(response.rect.center(), egui::vec2(42.0, 24.0));
    ui.painter()
        .rect_filled(rect, 12, if *value { GREEN } else { BORDER });
    let x = if *value {
        rect.right() - 12.0
    } else {
        rect.left() + 12.0
    };
    ui.painter()
        .circle_filled(egui::pos2(x, rect.center().y), 9.0, TEXT);
    response.on_hover_text(label)
}

pub fn setting(
    ui: &mut egui::Ui,
    icon: Icon,
    title: &str,
    description: &str,
    value: &mut bool,
    enabled: bool,
) -> bool {
    let mut changed = false;
    ui.add_enabled_ui(enabled, |ui| {
        ui.horizontal(|ui| {
            let (rect, _) = ui.allocate_exact_size(egui::vec2(26.0, 44.0), Sense::hover());
            paint_icon(ui.painter(), icon, rect.center(), 19.0, MUTED);
            let text_width = (ui.available_width() - 64.0).max(80.0);
            ui.allocate_ui_with_layout(
                egui::vec2(text_width, 44.0),
                egui::Layout::top_down(egui::Align::LEFT),
                |ui| {
                    ui.label(title);
                    ui.label(egui::RichText::new(description).size(13.0).color(MUTED));
                },
            );
            changed = switch(ui, title, value).changed();
        });
    });
    changed
}

pub fn key_value(ui: &mut egui::Ui, key: &str, value: &str) {
    ui.horizontal(|ui| {
        ui.label(egui::RichText::new(key).size(14.0).color(MUTED));
        ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
            ui.add(egui::Label::new(egui::RichText::new(value).size(14.0)).truncate())
                .on_hover_text(value);
        });
    });
}

pub fn status_dot(ui: &mut egui::Ui, label: &str, color: Color32) {
    ui.horizontal(|ui| {
        let (rect, _) = ui.allocate_exact_size(egui::vec2(12.0, 16.0), Sense::hover());
        ui.painter().circle_filled(rect.center(), 4.0, color);
        ui.label(egui::RichText::new(label).size(13.0).color(MUTED));
    });
}

pub fn text(
    painter: &egui::Painter,
    position: Pos2,
    label: &str,
    size: f32,
    color: Color32,
    right: f32,
) {
    let clip = Rect::from_min_max(
        egui::pos2(position.x, position.y - size),
        egui::pos2(right.max(position.x), position.y + size),
    );
    painter
        .with_clip_rect(painter.clip_rect().intersect(clip))
        .text(
            position,
            Align2::LEFT_CENTER,
            label,
            FontId::proportional(size),
            color,
        );
}

pub fn paint_icon(painter: &egui::Painter, icon: Icon, center: Pos2, size: f32, color: Color32) {
    let point = |x: f32, y: f32| center + egui::vec2(x, y) * size;
    let stroke = Stroke::new((size / 11.0).max(1.5), color);
    let path = |points: &[(f32, f32)]| {
        painter.add(egui::Shape::line(
            points.iter().map(|&(x, y)| point(x, y)).collect(),
            stroke,
        ));
    };
    match icon {
        Icon::Shield => {
            painter.add(egui::Shape::convex_polygon(
                [
                    (-0.38, -0.32),
                    (0.0, -0.48),
                    (0.38, -0.32),
                    (0.34, 0.15),
                    (0.20, 0.36),
                    (0.0, 0.50),
                    (-0.20, 0.36),
                    (-0.34, 0.15),
                ]
                .iter()
                .map(|&(x, y)| point(x, y))
                .collect(),
                color,
                Stroke::NONE,
            ));
            painter.add(egui::Shape::line(
                vec![point(-0.14, 0.0), point(-0.02, 0.12), point(0.18, -0.13)],
                Stroke::new(size * 0.09, BACKGROUND),
            ));
        }
        Icon::Home => {
            path(&[(-0.45, -0.02), (0.0, -0.42), (0.45, -0.02)]);
            path(&[
                (-0.31, -0.12),
                (-0.31, 0.40),
                (-0.10, 0.40),
                (-0.10, 0.12),
                (0.10, 0.12),
                (0.10, 0.40),
                (0.31, 0.40),
                (0.31, -0.12),
            ]);
        }
        Icon::Servers => {
            for y in [-0.28, 0.0, 0.28] {
                let points = (0..=24)
                    .map(|i| {
                        let t = i as f32 / 24.0 * TAU;
                        point(t.cos() * 0.35, y + t.sin() * 0.12)
                    })
                    .collect();
                painter.add(egui::Shape::line(points, stroke));
            }
            path(&[(-0.35, -0.28), (-0.35, 0.28)]);
            path(&[(0.35, -0.28), (0.35, 0.28)]);
        }
        Icon::Link => {
            path(&[
                (-0.05, -0.22),
                (0.10, -0.37),
                (0.31, -0.37),
                (0.43, -0.23),
                (0.43, -0.06),
                (0.16, 0.19),
                (0.0, 0.19),
            ]);
            path(&[
                (0.05, 0.22),
                (-0.10, 0.37),
                (-0.31, 0.37),
                (-0.43, 0.23),
                (-0.43, 0.06),
                (-0.16, -0.19),
                (0.0, -0.19),
            ]);
            path(&[(-0.15, 0.14), (0.15, -0.14)]);
        }
        Icon::Settings => {
            painter.circle_stroke(center, size * 0.27, stroke);
            painter.circle_stroke(center, size * 0.10, stroke);
            for i in 0..8 {
                let direction = Vec2::angled(i as f32 / 8.0 * TAU);
                painter.line_segment(
                    [
                        center + direction * size * 0.30,
                        center + direction * size * 0.43,
                    ],
                    stroke,
                );
            }
        }
        Icon::Power => {
            let points = (0..=48)
                .map(|i| {
                    let angle = -PI / 2.0 + 0.65 + i as f32 / 48.0 * (TAU - 1.30);
                    center + Vec2::angled(angle) * size * 0.36
                })
                .collect();
            painter.add(egui::Shape::line(points, stroke));
            path(&[(0.0, -0.47), (0.0, -0.04)]);
        }
        Icon::Lock => {
            painter.rect_stroke(
                Rect::from_min_max(point(-0.30, -0.06), point(0.30, 0.40)),
                3,
                stroke,
                egui::StrokeKind::Inside,
            );
            path(&[
                (-0.20, -0.06),
                (-0.20, -0.28),
                (-0.12, -0.40),
                (0.12, -0.40),
                (0.20, -0.28),
                (0.20, -0.06),
            ]);
            path(&[(0.0, 0.09), (0.0, 0.23)]);
        }
        Icon::Refresh => {
            let points = (0..=30)
                .map(|i| {
                    let angle = -0.7 + i as f32 / 30.0 * (TAU - 1.0);
                    center + Vec2::angled(angle) * size * 0.35
                })
                .collect();
            painter.add(egui::Shape::line(points, stroke));
            path(&[(0.0, -0.23), (0.29, -0.23), (0.29, -0.49)]);
        }
        Icon::Chevron => path(&[(-0.15, -0.30), (0.15, 0.0), (-0.15, 0.30)]),
        Icon::Star => {
            let points = (0..=10)
                .map(|i| {
                    let angle = -PI / 2.0 + i as f32 / 10.0 * TAU;
                    center + Vec2::angled(angle) * size * if i % 2 == 0 { 0.43 } else { 0.20 }
                })
                .collect();
            painter.add(egui::Shape::line(points, stroke));
        }
        Icon::Globe => {
            painter.circle_stroke(center, size * 0.40, stroke);
            path(&[(-0.38, 0.0), (0.38, 0.0)]);
            let points = (0..=32)
                .map(|i| {
                    let t = i as f32 / 32.0 * TAU;
                    point(t.cos() * 0.17, t.sin() * 0.40)
                })
                .collect();
            painter.add(egui::Shape::line(points, stroke));
        }
        Icon::Clock => {
            painter.circle_stroke(center, size * 0.40, stroke);
            path(&[(0.0, -0.24), (0.0, 0.0), (0.19, 0.10)]);
        }
        Icon::Activity => path(&[
            (-0.47, 0.0),
            (-0.26, 0.0),
            (-0.10, -0.35),
            (0.10, 0.35),
            (0.26, 0.0),
            (0.47, 0.0),
        ]),
    }
}

pub fn glow(painter: &egui::Painter, center: Pos2, radius: f32, connected: bool) {
    // Static, inexpensive concentric falloff: no continuous animation while idle.
    if connected {
        for step in (0..18).rev() {
            painter.circle_filled(
                center,
                radius + step as f32 * 4.0,
                Color32::from_rgba_unmultiplied(32, 200, 122, 3),
            );
        }
    }
}

/// Deliberately low-detail decorative continents, not server geolocation data.
pub fn world_map(painter: &egui::Painter, rect: Rect) {
    const LAND: &[&[(f32, f32)]] = &[
        &[
            (0.05, 0.22),
            (0.12, 0.12),
            (0.22, 0.10),
            (0.29, 0.19),
            (0.25, 0.29),
            (0.29, 0.35),
            (0.21, 0.44),
            (0.23, 0.52),
            (0.18, 0.49),
            (0.14, 0.36),
            (0.08, 0.33),
        ],
        &[
            (0.25, 0.04),
            (0.34, 0.05),
            (0.32, 0.21),
            (0.28, 0.24),
            (0.25, 0.16),
        ],
        &[
            (0.24, 0.48),
            (0.32, 0.49),
            (0.38, 0.59),
            (0.34, 0.72),
            (0.29, 0.89),
            (0.26, 0.79),
            (0.25, 0.65),
            (0.21, 0.55),
        ],
        &[
            (0.43, 0.30),
            (0.45, 0.22),
            (0.49, 0.20),
            (0.49, 0.10),
            (0.53, 0.08),
            (0.55, 0.20),
            (0.62, 0.12),
            (0.74, 0.12),
            (0.79, 0.08),
            (0.92, 0.18),
            (0.94, 0.30),
            (0.84, 0.33),
            (0.85, 0.42),
            (0.79, 0.46),
            (0.75, 0.57),
            (0.70, 0.48),
            (0.67, 0.40),
            (0.64, 0.52),
            (0.59, 0.39),
            (0.55, 0.40),
            (0.52, 0.31),
            (0.46, 0.36),
        ],
        &[
            (0.45, 0.37),
            (0.53, 0.38),
            (0.56, 0.47),
            (0.61, 0.48),
            (0.56, 0.59),
            (0.54, 0.75),
            (0.49, 0.79),
            (0.46, 0.68),
            (0.46, 0.57),
            (0.41, 0.50),
            (0.41, 0.43),
        ],
        &[
            (0.78, 0.69),
            (0.86, 0.65),
            (0.91, 0.73),
            (0.91, 0.81),
            (0.85, 0.85),
            (0.78, 0.79),
        ],
        &[(0.91, 0.86), (0.94, 0.82), (0.93, 0.91), (0.91, 0.94)],
        &[(0.87, 0.38), (0.89, 0.32), (0.90, 0.37), (0.88, 0.43)],
        &[(0.73, 0.58), (0.79, 0.59), (0.84, 0.64), (0.77, 0.64)],
    ];
    let columns = 96;
    let rows = 42;
    for y in 0..rows {
        for x in 0..columns {
            let point = (x as f32 / columns as f32, y as f32 / rows as f32);
            if LAND.iter().any(|polygon| inside_polygon(point, polygon)) {
                let position =
                    rect.min + egui::vec2(point.0 * rect.width(), point.1 * rect.height());
                painter.circle_filled(position, 1.05, Color32::from_rgb(19, 45, 48));
            }
        }
    }
    let points = (0..=80)
        .map(|i| {
            let t = i as f32 / 80.0;
            rect.min
                + egui::vec2(
                    t * rect.width(),
                    (0.70 - 0.46 * (PI * t).sin()) * rect.height(),
                )
        })
        .collect();
    painter.add(egui::Shape::line(
        points,
        Stroke::new(1.0, Color32::from_rgb(30, 80, 68)),
    ));
}

fn inside_polygon(point: (f32, f32), polygon: &[(f32, f32)]) -> bool {
    let mut inside = false;
    let mut previous = polygon[polygon.len() - 1];
    for &current in polygon {
        if (current.1 > point.1) != (previous.1 > point.1)
            && point.0
                < (previous.0 - current.0) * (point.1 - current.1) / (previous.1 - current.1)
                    + current.0
        {
            inside = !inside;
        }
        previous = current;
    }
    inside
}

/// ISO label instead of platform-dependent flag emoji or guessed locations.
pub fn country_badge(painter: &egui::Painter, center: Pos2, country: &str) {
    let rect = Rect::from_center_size(center, egui::vec2(38.0, 30.0));
    painter.rect_filled(rect, 7, RAISED);
    let code = country.trim().to_ascii_uppercase();
    if code.len() == 2 && code.bytes().all(|byte| byte.is_ascii_alphabetic()) {
        painter.text(
            center,
            Align2::CENTER_CENTER,
            code,
            FontId::proportional(13.0),
            GREEN,
        );
    } else {
        paint_icon(painter, Icon::Globe, center, 21.0, MUTED);
    }
}
