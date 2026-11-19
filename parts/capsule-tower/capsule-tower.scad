// Rotating capsule tower: 6 rows x 5 capsules. The printed foil faces outward,
// the capsule body sits in a channel inside the tower.
// Capsules load from the top and are taken from the bottom of a row.

/* Largest capsule the tower is built for.
   Published: Caffitaly/Cafissimo 26.6 high, seat 39.5, flange 45.5 x 1.0;
   K-fee 27.6 high, seat 38.8, flange 45.4 x 1.0. Smallest rim measured: 44. */
rim_max = 45.5;
rim_min = 44;
rim_t = 1.0;
body_max = 39.5;
cap_h_max = 27.6;

/* Capsule used in the simulation and the picture */
cap_rim = 44;
cap_body = 39.5;
cap_tip = 33;
cap_h = 26.6;

rows = 6;
per_row = 5;

/* Fit */
side_gap = 0.6;     // largest rim to groove side, per side
depth_gap = 1.0;    // rim thickness play in the groove
body_gap = 0.8;     // body to channel side, per side
tip_gap = 1.5;      // tallest capsule tip to channel back
pin_gap = 0.4;      // radial, pivot

/* Tower */
S = 38.5;           // visible opening in front of the foil
lip = 2;            // lip thickness in front of the rim
back_r = 40;        // centre to the back of a body channel
floor_z = 8;
top_extra = 12.1;
lower_lip_h = 15;   // retaining lip of the bottom capsule
window_top = 46;    // where the upper lips start, above the row floor
core_wall = 1.7;
use_pockets = false;

/* Base */
base_d = 176;
base_h = 10;
pin_d = 22;
pin_h = 32;
ring_r = 32;
ring_h = 2;          // keeps the tower corners off the base if it is pushed sideways

/* Stamp on the top face */
stamp_top = "KHE.EE";
stamp_bottom = "BARISTA";
stamp_height = 0.8;
stamp_cap = 6.5;

mode = "assembly";
lift = 0;
pull = 0;

$fn = 96;
eps = 0.01;

W = rim_max + 2 * side_gap;
G = rim_t + depth_gap;
B = body_max + 2 * body_gap;
body_depth = cap_h_max - rim_t + tip_gap;
A = back_r + body_depth + G + lip;
H = floor_z + per_row * rim_max + top_extra;
seat = 0.3;
cz = seat + (rim_min + rim_max) / 4;    // arc centre of the lower lip

function hex_r(a) = a / cos(30);

module slot_2d() {
    translate([-S / 2, cz]) square([S, H]);
    translate([0, cz]) circle(d = S);
}

module window_2d() {
    slope = (W - S) / 2;
    difference() {
        polygon([[-W / 2, -1], [W / 2, -1], [W / 2, window_top - slope],
                 [S / 2, window_top], [-S / 2, window_top],
                 [-W / 2, window_top - slope]]);
        difference() {
            translate([-W / 2 - 1, -2]) square([W + 2, lower_lip_h + 2]);
            translate([0, cz]) circle(d = S);
        }
    }
}

module row_cut() {
    translate([0, 0, floor_z]) {
        translate([-B / 2, back_r, 0]) cube([B, body_depth + eps, H]);
        translate([-W / 2, A - lip - G, 0]) cube([W, G, H]);
        translate([0, A + 1, 0]) rotate([90, 0, 0])
            linear_extrude(lip + 1 + eps) union() { slot_2d(); window_2d(); }
        // Guides a falling rim behind the lower lip.
        rotate([90, 0, 90]) linear_extrude(W, center = true)
            polygon([[A - lip - eps, lower_lip_h + eps], [A - lip + 1.2, lower_lip_h + eps],
                     [A - lip - eps, lower_lip_h - 1.2]]);
    }
}

module cavity() {
    a = back_r - core_wall;
    roof = a * 1.25;
    translate([0, 0, floor_z]) cylinder(r = hex_r(a), h = H - floor_z - roof - 4, $fn = 6);
    translate([0, 0, H - roof - 4 - eps])
        cylinder(r1 = hex_r(a), r2 = 0.2, h = roof, $fn = 6);
}

// Closed pockets in the solid corners between rows save most of the filament.
module corner_pockets() {
    translate([0, 0, floor_z]) linear_extrude(H - floor_z - 3)
        offset(r = -core_wall) difference() {
            intersection() {
                circle(r = hex_r(A), $fn = 6);
                circle(r = hex_r(A) - 2);
            }
            circle(r = hex_r(back_r), $fn = 6);
            for (i = [0 : rows - 1]) rotate(i * 360 / rows) {
                translate([-B / 2, back_r - eps]) square([B, body_depth + 2 * eps]);
                translate([-W / 2, A - lip - G]) square([W, G + lip + 1]);
            }
        }
}

module tower() {
    socket_d = pin_d + 2 * pin_gap;
    difference() {
        union() {
            difference() {
                intersection() {
                    cylinder(r = hex_r(A), h = H, $fn = 6);
                    cylinder(r = hex_r(A) - 2, h = H);
                }
                cavity();
                if (use_pockets) corner_pockets();
            }
            cylinder(d = socket_d + 6, h = pin_h + 4);
        }
        for (i = [0 : rows - 1]) rotate(i * 360 / rows) row_cut();
        translate([0, 0, -eps]) cylinder(d = socket_d, h = pin_h + 5);
        translate([0, 0, -eps]) cylinder(d1 = socket_d + 2, d2 = socket_d, h = 1);
    }
    // Raised, so a filament change at this height prints only the stamp in white.
    translate([0, 0, H - eps]) linear_extrude(stamp_height + eps) stamp_2d();
}

// One row, two capsules high, to try the fit before the full print.
module fit_test() {
    intersection() {
        tower();
        translate([-(W / 2 + 8), back_r - 4, 0]) cube([W + 16, A - back_r + 5, floor_z + 2 * rim_max + 8]);
    }
}

stamp_font = "Liberation Sans:style=Bold";
// Advance widths of the stamp font, in em.
glyphs = [["-", .333], [".", .278], ["0", .556], ["1", .556], ["2", .556], ["3", .556], ["4", .556],
          ["5", .556], ["6", .556], ["7", .556], ["8", .556], ["9", .556], ["A", .722], ["B", .722],
          ["C", .722], ["D", .722], ["E", .667], ["F", .611], ["G", .778], ["H", .722], ["I", .278],
          ["J", .556], ["K", .722], ["L", .611], ["M", .833], ["N", .722], ["O", .778], ["P", .667],
          ["Q", .778], ["R", .722], ["S", .667], ["T", .611], ["U", .722], ["V", .667], ["W", .944],
          ["X", .667], ["Y", .667], ["Z", .611], ["Ä", .722], ["Õ", .778], ["Ö", .778], ["Ü", .722], ["Š", .667], ["Ž", .611]];
function glyph(c) = let(i = search([c], glyphs)[0])
    assert(is_num(i), str("stamp letter missing from the glyph table: ", c))
    glyphs[i][1] * stamp_cap * 1.39;
function run(str, track, n) = n <= 0 ? 0 : glyph(str[n - 1]) + track + run(str, track, n - 1);
function run_len(str, track) = run(str, track, len(str)) - track;
function run_mid(str, track, i) = run(str, track, i) + glyph(str[i]) / 2;
function arc_deg(len_mm, r) = len_mm / r * 180 / PI;

module arc_over(str, r, track) {
    rm = r + stamp_cap / 2;
    for (i = [0 : len(str) - 1])
        rotate(-arc_deg(run_mid(str, track, i) - run_len(str, track) / 2, rm))
            translate([0, r]) text(str[i], size = stamp_cap, font = stamp_font, halign = "center");
}

module arc_under(str, r, track) {
    rm = r - stamp_cap / 2;
    for (i = [0 : len(str) - 1])
        rotate(arc_deg(run_mid(str, track, i) - run_len(str, track) / 2, rm))
            translate([0, -r]) text(str[i], size = stamp_cap, font = stamp_font, halign = "center");
}

module ring_2d(r, w) { difference() { circle(r = r + w / 2); circle(r = r - w / 2); } }

module steam_2d(x0) {
    steps = 14;
    for (i = [0 : steps - 1]) hull() for (j = [i, i + 1])
        translate([x0 + 1.3 * sin(j / steps * 360), 5.5 + j / steps * 10]) circle(d = 1.5, $fn = 16);
}

module cup_2d() {
    translate([-1.5, 0]) {
        hull() {
            translate([-9.2, 1.2]) circle(r = 0.8, $fn = 24);
            translate([9.2, 1.2]) circle(r = 0.8, $fn = 24);
            translate([-5.5, -8.5]) circle(r = 2, $fn = 32);
            translate([5.5, -8.5]) circle(r = 2, $fn = 32);
        }
        translate([9.5, -3]) difference() { circle(r = 4.6); circle(r = 2.5); }
    }
    hull() {
        translate([-13, -12.6]) circle(d = 1.6, $fn = 16);
        translate([10, -12.6]) circle(d = 1.6, $fn = 16);
    }
    for (x = [-6.5, -1.5, 3.5]) steam_2d(x);
}

// Round stamp: one line over the top, one under it, a cup in the middle.
module stamp_2d() {
    ring_2d(38, 1.1);
    ring_2d(25.6, 0.9);
    arc_over(stamp_top, 28.6, 0.7);
    arc_under(stamp_bottom, 35, 1.8);
    for (side = [-1, 1]) rotate(side * 108) translate([0, 31.8]) circle(d = 2.6, $fn = 24);
    cup_2d();
}

module base() {
    rotate_extrude($fn = 180) polygon([
        [0, 0], [base_d / 2 - 1, 0], [base_d / 2, 1], [base_d / 2, base_h - 3],
        [base_d / 2 - 3, base_h], [ring_r + 1.5, base_h],
        [ring_r + 0.5, base_h + ring_h], [ring_r - 0.5, base_h + ring_h],
        [ring_r - 1.5, base_h], [pin_d / 2, base_h],
        [pin_d / 2, base_h + pin_h - 2], [pin_d / 2 - 2, base_h + pin_h], [0, base_h + pin_h]
    ]);
}

// Foil faces +y, the body points toward the tower centre.
module capsule() {
    translate([0, A - lip - depth_gap / 2, cap_rim / 2]) rotate([90, 0, 0]) {
        cylinder(d = cap_rim, h = rim_t);
        translate([0, 0, rim_t - eps]) cylinder(d1 = cap_body, d2 = cap_tip, h = cap_h - rim_t);
    }
}

module label(word) {
    translate([0, A - lip - depth_gap / 2 + 0.05, cap_rim / 2]) rotate([90, 0, 180])
        linear_extrude(0.1) text(word, size = 5, halign = "center", valign = "center");
}

module placed(n = 0, dz = 0, dy = 0) {
    translate([0, dy, floor_z + seat + n * cap_rim + dz]) capsule();
}

module hits(steps) {
    intersection() {
        tower();
        union() { for (s = steps) placed(0, s[0], s[1]); }
    }
}

palette = ["#6f3b22", "#b5892f", "#2f5d8a", "#8f2f35", "#3f6f4e", "#55504a"];
names = ["Espresso", "Crema", "Lungo", "Ristretto", "Mild", "Decaf"];

if (mode == "tower") tower();
else if (mode == "base") base();
else if (mode == "test") fit_test();
else if (mode == "stamp") linear_extrude(1) stamp_2d();
else if (mode == "stamp_open") linear_extrude(1) offset(r = 0.3) offset(r = -0.3) stamp_2d();
else if (mode == "stamp_view") {
    color("#26262a") translate([0, 0, -1]) cylinder(r = 46, h = 1, $fn = 6);
    color("#f2eee6") linear_extrude(0.1) stamp_2d();
}
else if (mode == "rest") intersection() { tower(); for (n = [0 : per_row - 1]) placed(n); }
else if (mode == "load") hits([for (z = [0 : 2 : H - floor_z]) [z, 0]]);
else if (mode == "lift") hits([for (z = [0 : 0.5 : lift]) [z, 0]]);
else if (mode == "pull") hits([for (y = [0 : 1 : cap_h + 8]) [lift, y]]);
else if (mode == "retain") intersection() { tower(); placed(0, 0, pull); }
else if (mode == "retain2") intersection() { tower(); placed(1, 0, pull); }
else if (mode == "clearance") echo(side_clearance = (W - cap_rim) / 2);
else {
    color("#1d1d1f") base();
    translate([0, 0, base_h + ring_h]) {
        color("#2a2a2d") tower();
        for (i = [0 : rows - 1]) rotate(i * 360 / rows)
            for (n = [0 : per_row - 1 - (i == 3 ? 1 : 0)]) {
                color(palette[i]) placed(n);
                color("#f4efe6") translate([0, 0, floor_z + seat + n * cap_rim]) label(names[i]);
            }
    }
}
