// Yarn bowl for a ball of thick yarn (about 12 cm). Twisted ribs on the outside,
// a smooth inside, and a yarn guide that runs down from the rim and turns up
// into a hook. A maker's stamp is set into the underside, printed in a second
// colour in the bottom three layers.

/* Stamp. The family's own text is a private parameter set. */
stamp_top = "KHE.EE";
stamp_bottom = "HANDCRAFT CO";
greeting = "";     // an arc of words round the stamp, empty for none
date_text = "";    // under the stamp, empty for none

mode = "bowl";     // bowl | stamp | clearance | hold_end | hold_low
yarn_d = 6;        // probes: yarn thickness
lift = 0;          // probes: how far the yarn is pulled straight up

$fn = 160;

H = 112;           // height
r_base = 66;       // outer radius at the foot
r_belly = 98;      // widest outer radius
z_belly = 66;
r_rim = 92;        // the rim tucks in to keep the ball inside
wall = 2.4;
floor_t = 3.2;
slot_w = 10.4;     // the yarn guide's width

stamp_font = "Liberation Sans:style=Bold";
greeting_font = "Source Serif 4:style=Medium Italic";
stamp_cap = 6.5;
greeting_size = 7;
groove = 0.68;     // three layers: 0.2 + 0.24 + 0.24

// Outer radius at height z: a soft curve out to the belly, then in to the rim.
function ro(z) =
    z <= z_belly
        ? r_base + (r_belly - r_base) * sin(90 * z / z_belly)
        : r_belly - (r_belly - r_rim) * pow((z - z_belly) / (H - z_belly), 2);

function tilt(z) = atan(ro(min(z + 0.5, H)) - ro(max(z - 0.5, 0)));

// Places children across the wall at angle a and height z, their z axis along the wall's normal.
module on_wall(a, z) {
    rotate([0, 0, a]) translate([ro(z), 0, z]) rotate([0, 90 + tilt(z), 0]) children();
}

// A round cutter of width w across the wall; the guide is the hull of a chain of them.
module cutter(a, z, w) { on_wall(a, z) translate([0, 0, -wall - 6]) cylinder(d = w, h = wall + 12); }

/* Yarn guide: a quarter ellipse that leaves the rim straight down and ends
   running along the wall, then a hook that turns up. A pull from above carries
   the yarn into the hook's closed end instead of back up the long arm. */
slot_sweep = 30;   // degrees round the bowl
slot_drop = 50;    // mm below the rim
slot_flare = 10;   // extra width at the rim, a funnel that leads the yarn in
slot_flare_h = 16;
hook_r = 8;        // turning radius of the hook's centre line
hook_up = 6;       // straight rise after the turn
z_low = H - slot_drop;
hook_deg = arc_deg(hook_r, ro(z_low));

function slot_width(z) = let(s = max(0, min(1, (z - (H - slot_flare_h)) / slot_flare_h)))
    slot_w + slot_flare * s * s;
function slot_path() = concat(
    [for (t = [0 : 0.02 : 1.0001])
        let(z = H + 4 - (slot_drop + 4) * sin(90 * t))
        [slot_sweep * (1 - cos(90 * t)), z, slot_width(z)]],
    [for (u = [0.1 : 0.1 : 1.0001])
        [slot_sweep + hook_deg * sin(90 * u), z_low + hook_r - hook_r * cos(90 * u), slot_w]],
    [for (v = [0.25 : 0.25 : 1.0001])
        [slot_sweep + hook_deg, z_low + hook_r + hook_up * v, slot_w]]);
slot = slot_path();
hook_end = slot[len(slot) - 1];

module yarn_slot() {
    for (i = [0 : len(slot) - 2]) hull() {
        cutter(slot[i][0], slot[i][1], slot[i][2]);
        cutter(slot[i + 1][0], slot[i + 1][1], slot[i + 1][2]);
    }
}

/* Body: ribs on the outer wall that twist as they rise and fade out at the
   foot and the rim, and give way to a smooth patch round the guide. The inner
   surface is the outer one moved in by `wall`, horizontally. */
ribs = 16;
rib_amp = 5;
rib_twist = 45;    // degrees each rib turns from foot to rim
M = 288;           // points round
K = 84;            // rings up
function smooth(f) = f * f * (3 - 2 * f);
function fade(z) = smooth(max(0, min(1, z / 26, (H - z) / 14)));
function wrap(t) = let(u = (t % 360 + 360) % 360) u > 180 ? u - 360 : u;
function guide_fade(t) = let(u = wrap(t), d = max(0, -6 - u, u - (slot_sweep + hook_deg + 8))) smooth(min(1, d / 14));
function wave_r(z, t) = ro(z) + rib_amp * fade(z) * guide_fade(t) * (1 + cos(ribs * t + ribs * rib_twist * z / H)) / 2;
function o_idx(k, j) = k * M + (j % M);
function i_idx(k, j) = o_idx(K + 1 + k, j);

module body() {
    function surface(z0, off) = [for (k = [0 : K]) for (j = [0 : M - 1])
        let(z = z0 + (H - z0) * k / K, t = 360 * j / M, r = wave_r(z, t) - off) [r * cos(t), r * sin(t), z]];
    cb = 2 * (K + 1) * M;
    ci = cb + 1;
    faces = concat(
        [for (k = [0 : K - 1]) for (j = [0 : M - 1]) [o_idx(k, j), o_idx(k + 1, j), o_idx(k + 1, j + 1), o_idx(k, j + 1)]],
        [for (k = [0 : K - 1]) for (j = [0 : M - 1]) [i_idx(k, j), i_idx(k, j + 1), i_idx(k + 1, j + 1), i_idx(k + 1, j)]],
        [for (j = [0 : M - 1]) [cb, o_idx(0, j), o_idx(0, j + 1)]],
        [for (j = [0 : M - 1]) [ci, i_idx(0, j + 1), i_idx(0, j)]],
        [for (j = [0 : M - 1]) [o_idx(K, j), i_idx(K, j), i_idx(K, j + 1), o_idx(K, j + 1)]]
    );
    polyhedron(concat(surface(0, 0), surface(floor_t, wall), [[0, 0, 0], [0, 0, floor_t]]), faces, convexity = 6);
    // a round top on the rim, so yarn slides over it
    translate([0, 0, H]) rotate_extrude() translate([ro(H) - wall / 2, 0]) circle(d = wall);
}

/* Stamp: the top line over a yarn ball, the bottom line under it, and an
   optional greeting and date round the outside. */
function adv(c, size, font) = textmetrics(c, size = size, font = font).advance[0];
function sum_to(v, n) = n <= 0 ? 0 : v[n - 1] + sum_to(v, n - 1);
function arc_deg(len_mm, r) = len_mm / r * 180 / PI;

// Letters stand on a circle of radius r with their tops outward (over) or
// hang from it with their tops toward the centre (under).
module arc_text(str, r, size, font, track, over) {
    n = len(str);
    if (n > 0) {
        a = [for (c = str) adv(c, size, font)];
        total = sum_to(a, n) + track * (n - 1);
        rm = over ? r + size / 2 : r - size / 2;
        for (i = [0 : n - 1]) if (str[i] != " ") {
            mid = sum_to(a, i) + track * i + a[i] / 2 - total / 2;
            rotate(over ? -arc_deg(mid, rm) : arc_deg(mid, rm))
                translate([0, over ? r : -r]) text(str[i], size = size, font = font, halign = "center");
        }
    }
}

module ring_2d(r, w) { difference() { circle(r = r + w / 2); circle(r = r - w / 2); } }

module strand_2d(pts, d) {
    for (i = [0 : len(pts) - 2]) hull() {
        translate(pts[i]) circle(d = d, $fn = 16);
        translate(pts[i + 1]) circle(d = d, $fn = 16);
    }
}

// A ball of yarn with two knitting needles through it and a loose end.
module yarn_ball_2d() {
    c = [0, -1.5];
    rb = 9.5;
    difference() {
        for (side = [-1, 1]) {
            strand_2d([[side * -9.5, -13], [side * 10.5, 15]], 1.6);
            translate([side * 11.2, 16]) circle(d = 3.4, $fn = 24);
        }
        translate(c) circle(r = rb + 1.3);
    }
    translate(c) {
        ring_2d(rb, 1.4);
        intersection() {
            circle(r = rb - 0.4);
            union() {
                for (k = [0 : 2]) translate([-7, 7]) ring_2d(6.5 + k * 3.4, 1.0);
                // the strands that wrap the other way, past the outermost arc
                difference() {
                    for (k = [0 : 1]) translate([11, -5]) ring_2d(5.5 + k * 3.2, 1.0);
                    translate([-7, 7]) circle(r = 6.5 + 2 * 3.4 + 1.6);
                }
            }
        }
    }
    strand_2d([for (t = [0 : 0.025 : 1.0001]) [7 + 12 * t, -9.5 - 3 * t - 1.8 * sin(300 * t)]], 1.2);
}

module stamp_2d() {
    ring_2d(38, 1.1);
    ring_2d(25.6, 0.9);
    arc_text(stamp_top, 28.6, stamp_cap, stamp_font, 0.7, true);
    arc_text(stamp_bottom, 35, stamp_cap, stamp_font, 0.3, false);
    for (side = [-1, 1]) rotate(side * 95) translate([0, 31.8]) circle(d = 2.6, $fn = 24);
    yarn_ball_2d();
    arc_text(greeting, 44, greeting_size, greeting_font, 0.15, true);
    arc_text(date_text, 55.5, greeting_size, greeting_font, 0.6, false);
}

// Mirrored, so it reads correctly from below; widened a little so the
// thinnest strokes still print on the first layer.
module stamp_flat() { mirror([1, 0, 0]) offset(r = 0.2) stamp_2d(); }

module bowl() {
    difference() {
        body();
        yarn_slot();
        translate([0, 0, -1]) linear_extrude(1 + groove) stamp_flat();
    }
}

// The white part: it fills the stamp's cut exactly.
module stamp_inlay() { linear_extrude(groove) stamp_flat(); }

if (mode == "bowl") bowl();
else if (mode == "stamp") stamp_inlay();
else if (mode == "clearance") echo(yarn_clearance = (slot_w - yarn_d) / 2);
// the yarn, as a length across the wall, pulled straight up from the hook's
// closed end or from the bottom of the turn
else if (mode == "hold_end") intersection() { bowl(); cutter(hook_end[0], hook_end[1] + lift, yarn_d); }
else if (mode == "hold_low") intersection() { bowl(); cutter(slot_sweep, z_low + lift, yarn_d); }
