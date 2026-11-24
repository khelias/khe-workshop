// Star egg: the Soma egg at 0.7 of its size, with a belt of white eight-pointed
// stars inlaid in each half, stripes in colour bands and KHE.ee on the bottom.
// Every colour region is its own export, so one print is a set of parts with
// one filament each.

include <../soma-egg/soma-egg.scad>
use <../../fonts/FamiljenGrotesk-SemiBold.ttf>

// The Soma egg draws these modes itself, at this size; every other mode is drawn below.
library = !(mode == "egg" || mode == "pieces" || mode == "test_base" || mode == "test_cap"
            || mode == "test_piece" || mode == "solved_piece" || mode == "closed" || mode == "raised"
            || mode == "thread" || mode == "walls");

u = 6;
egg_b = 40.6;
egg_l = 53.55;
egg_w = 3.15;
egg_zc = -2.1;
bottom_z = -26.32;
spigot_h = 6;
pattern = "none";

/* Colours, by the slot of the plate's filament */
WHITE = 0;
GREEN = 1;
YELLOW = 2;
RED = 3;

/* Inlay */
depth = 0.8;       // radial: two perimeters
depth_v = 1.0;     // where the cap's shell faces up: five layers, so white covers red

/* Stripes: [z0, z1, colour], full sections of the half, so each costs one change a plate */
base_bands = [[bottom_z - 1, -19.2, GREEN], [-18.6, -17.8, YELLOW], [-3.6, -2.8, GREEN], [-1.6, -0.6, YELLOW]];
cap_bands = [[0.6, 1.6, YELLOW], [2.8, 3.6, GREEN], [14.6, 15.4, GREEN], [16.4, top_z + 1, GREEN]];
band = 0;

/* Belts of eight stars */
base_belt = [-10.2, 0];     // [z, angle of the first star]
cap_belt = [8.6, 22.5];
star_s = 2.55;

/* Bottom mark: a kaheksakand over KHE with a smaller .ee, 0.6 mm deep */
F = "Familjen Grotesk:style=SemiBold";
mark_depth = 0.6;
grow = 0.05;       // thickens small strokes so none is under 0.5 mm

/* The pieces printed in each colour, by their index in `pieces` */
piece_colours = [RED, WHITE, YELLOW, GREEN, RED, WHITE, GREEN];
slot = RED;

assert(let(f = fontmetrics(font = F).font) f.family == "Familjen Grotesk" && f.style == "SemiBold",
       "the mark font did not load");

function slope(z) = (egg_r(z + 0.05) - egg_r(z - 0.05)) / 0.1;

// The frame of the shell's surface at angle t and height z: x along the belt, y up the
// shell, z out of it.
module at(t, z) {
    s = slope(z);
    l = sqrt(1 + s * s);
    n = [cos(t), sin(t), -s] / l;
    et = [-sin(t), cos(t), 0];
    em = cross(n, et);
    multmatrix([[et[0], em[0], n[0], egg_r(z) * cos(t)],
                [et[1], em[1], n[1], egg_r(z) * sin(t)],
                [et[2], em[2], n[2], z],
                [0, 0, 0, 1]]) children();
}

module shape(t, z, spin = 0) at(t, z) rotate(spin) linear_extrude(4, center = true) children();

module kaheksakand2d(s, gap) for (k = [0 : 7]) rotate(45 * k)
    offset(delta = -gap) polygon([[0, 0], s * [cos(-22.5), sin(-22.5)],
        s * [cos(-22.5) + cos(22.5), sin(-22.5) + sin(22.5)], s * [cos(22.5), sin(22.5)]]);

module diamond(w, h) polygon([[0, -h], [w, 0], [0, h], [-w, 0]]);

// Eight stars with a diamond between each pair and a small one above and below it.
// The diamonds stay inside the stars' layers, so they cost no colour change.
module belt(z, off) for (i = [0 : 7]) {
    t = off + 45 * i;
    shape(t, z, 90) difference() { kaheksakand2d(star_s, 0.28); circle(d = 2.2, $fn = 24); }
    shape(t + 22.5, z) diamond(1.25, 2.3);
    for (dz = [-3.5, 3.5]) shape(t + 22.5, z + dz) diamond(0.9, 0.9);
}

module skin(z0, z1, cap = false) {
    zs = [for (i = [0 : steps]) z0 + (z1 - z0) * i / steps];
    if (cap) difference() { shell(0, top_z); translate([0, 0, -depth_v]) shell(0, top_z); }
    rotate_extrude() polygon(concat([for (z = zs) [chamfered(z) + 0.01, z]],
                                    [for (i = [steps : -1 : 0]) [max(0, chamfered(zs[i]) - depth), zs[i]]]));
}

// The stars' cutter stands 0.01 mm proud of the shell, so the body it is cut from keeps
// no face in common with it.
module star_cutter(is_cap) {
    if (is_cap) intersection() { skin(0, top_z, true); belt(cap_belt[0], cap_belt[1]); }
    else intersection() { skin(bottom_z, 0); belt(base_belt[0], base_belt[1]); }
}

module stars(is_cap) intersection() { star_cutter(is_cap); if (is_cap) cap(); else base(); }

module glyphs(s, size) offset(delta = grow) text(s, size = size, font = F);

function advance(s, size) = textmetrics(s, size = size, font = F).advance[0];

// Drawn as it reads from below; part 0 is white, part 1 the accent.
module mark2d(part) {
    size = 3.7;
    w1 = advance("KHE", size);
    w = w1 + 0.04 * size + advance(".ee", 0.7 * size);
    if (part == 0) translate([0, 3.2]) rotate(22.5) kaheksakand2d(2.15, 0.2);
    translate([-w / 2, -4.3]) {
        if (part == 0) glyphs("KHE", size);
        if (part == 1) translate([w1 + 0.04 * size, 0]) glyphs(".ee", 0.7 * size);
    }
}

module mark(part) intersection() {
    translate([0, 0, bottom_z - 1]) linear_extrude(1.6) mirror([1, 0, 0]) mark2d(part);
    translate([0, 0, bottom_z]) cylinder(r = 15, h = mark_depth);
}

module slab(b) translate([-egg_b, -egg_b, b[0]]) cube([2 * egg_b, 2 * egg_b, b[1] - b[0]]);

module base_band(n) difference() { intersection() { base(); slab(base_bands[n]); } mark(0); mark(1); }

module cap_band(n) intersection() { cap(); slab(cap_bands[n]); }

module base_body() difference() {
    base();
    star_cutter(false);
    mark(0);
    mark(1);
    for (b = base_bands) slab(b);
}

module cap_body() difference() {
    cap();
    star_cutter(true);
    for (b = cap_bands) slab(b);
}

// Every colour region of a half, the body first.
module base_regions(i) {
    if (i == 0) base_body();
    else if (i == 1) stars(false);
    else if (i == 2) mark(0);
    else if (i == 3) mark(1);
    else base_band(i - 4);
}

module cap_regions(i) {
    if (i == 0) cap_body();
    else if (i == 1) stars(true);
    else cap_band(i - 2);
}

base_count = 4 + len(base_bands);
cap_count = 2 + len(cap_bands);

module pieces_in(colour) {
    chosen = [for (i = [0 : len(pieces) - 1]) if (piece_colours[i] == colour) i];
    for (k = [0 : len(chosen) - 1]) translate([k * 4 * u, 0, 0]) piece(pieces[chosen[k]][1]);
}

if (mode == "base") base_body();
else if (mode == "cap") cap_body();
else if (mode == "base_stars") stars(false);
else if (mode == "cap_stars") stars(true);
else if (mode == "base_mark") mark(0);
else if (mode == "base_mark_accent") mark(1);
else if (mode == "base_band") base_band(band);
else if (mode == "cap_band") cap_band(band);
else if (mode == "base_object") base();
else if (mode == "cap_object") cap();
else if (mode == "pieces_in") pieces_in(slot);
// Probes, each over both halves: no two regions overlap, and together they are the half exactly.
else if (mode == "overlap") {
    for (i = [0 : base_count - 1], j = [0 : base_count - 1]) if (i < j)
        intersection() { base_regions(i); base_regions(j); }
    for (i = [0 : cap_count - 1], j = [0 : cap_count - 1]) if (i < j)
        intersection() { cap_regions(i); cap_regions(j); }
}
else if (mode == "union_minus_parts") {
    difference() { base(); for (i = [0 : base_count - 1]) base_regions(i); }
    difference() { cap(); for (i = [0 : cap_count - 1]) cap_regions(i); }
}
else if (mode == "parts_minus_union") {
    difference() { for (i = [0 : base_count - 1]) base_regions(i); base(); }
    difference() { for (i = [0 : cap_count - 1]) cap_regions(i); cap(); }
}
else assert(!library, str("no mode ", mode));
