// Surprise egg: the Soma egg's thread on a longer egg, hollow for a small toy that
// rattles inside. The seam sits a third of the way up, where the white base meets
// the red cap and the cap's spiral flutes begin, so the thread never shows. The
// cavity is the egg's outline set in by one wall, and it never overhangs more than
// 45 degrees as printed: the base stands on its foot, the cap on its rim.

include <../soma-egg/soma-egg.scad>

// The Soma egg draws nothing of its own here; every mode is drawn below.
library = true;

/* Egg: longer and narrower than the Soma egg, its widest point just above the seam */
egg_b = 56;
egg_l = 82;
egg_w = 5;
egg_zc = 7;
bottom_z = -30.6;  // flat foot, where the overhang reaches 60 degrees

wall = 1.6;        // shell thickness along its normal, under the flutes' troughs on the cap
floor_t = 2;       // the base's floor
mode = "egg";

/* Spiral flutes on the cap */
flute_n = 20;
flute_h = 1.2;     // depth of a trough
flute_twist = 70;  // degrees the flutes turn from the seam to the tip
flute_in = 12;     // they deepen over the thread, so its wall keeps 1.6 mm
flute_out = 0.35;  // and fade over this share of the cap below the tip
flute_nt = 240;    // points around a ring: 12 a flute
flute_nz = 110;    // rings from the seam to the tip

r_bore = r_core - wall_min;                // the opening through the spigot
cap_bore = r_core + thread_gap;            // the cap's bore, as the Soma cap's
z_floor = bottom_z + floor_t;
z_apex = top_z - wall;                     // the cavity's tip, under the shell's
cavity_steps = 120;

function smooth01(x) = let (c = min(1, max(0, x))) c * c * (3 - 2 * c);

// Depth of the flutes' troughs at height z on the cap.
function flute_depth(z) = flute_h * smooth01(z / flute_in) * pow(min(1, max(0, (top_z - z) / (flute_out * top_z))), 0.8);

// The cap's surface: the egg's outline, cut by the flutes' troughs.
function flute_r(z, t) = chamfered(z) - flute_depth(z) * 0.5 * (1 + cos(flute_n * (t + flute_twist * z / top_z)));

// The cap's outer solid: rings packed toward the tip, where the outline turns fastest.
module fluted_shell() {
    zs = [for (i = [0 : flute_nz - 1]) top_z * sin(90 * i / flute_nz)];
    pts = concat(
        [for (z = zs, j = [0 : flute_nt - 1]) let (t = 360 * j / flute_nt, r = flute_r(z, t)) [r * cos(t), r * sin(t), z]],
        [[0, 0, 0], [0, 0, top_z]]);
    n = flute_nt;
    last = (flute_nz - 1) * n;
    sides = [for (i = [0 : flute_nz - 2], j = [0 : n - 1])
        let (a = i * n + j, b = i * n + (j + 1) % n) [a, a + n, b + n, b]];
    bottom = [for (j = [0 : n - 1]) [len(pts) - 2, j, (j + 1) % n]];
    tip = [for (j = [0 : n - 1]) [len(pts) - 1, last + (j + 1) % n, last + j]];
    polyhedron(pts, concat(sides, bottom, tip));
}

// The slope of the egg's outline, dr/dz.
function egg_slope(z) = (egg_r(z + 0.01) - egg_r(z - 0.01)) / 0.02;

// A point of the outline moved inward by w along its normal.
function inset(z, w) = let (d = egg_slope(z), l = sqrt(1 + d * d)) [egg_r(z) - w / l, z + w * d / l];

// The inset outline from z0 to z1, w deep at each height, each point held inside the limit r <= f(z).
function inset_run(z0, z1, w, limit) = [for (i = [0 : cavity_steps]) let (z = z0 + (z1 - z0) * i / cavity_steps, p = inset(z, w(z)))
    [min(p[0], limit(p[1])), p[1]]];

// The base: the inset bowl from its floor up, narrowing at 45 degrees into the bore.
base_run = [for (p = inset_run(bottom_z, 0, function(z) wall, function(z) r_bore - z)) if (p[1] >= z_floor && p[1] <= 0) p];
base_profile = concat([[base_run[0][0], z_floor]], base_run, [[r_bore, 0], [r_bore, spigot_h + 1]]);

// The cap: the inset dome under the flutes from the top of the bore to the tip, closing at 45 degrees.
cap_run = [for (p = inset_run(ceil_z - 2 * wall, top_z, function(z) wall + flute_depth(z), function(z) z_apex - z))
    if (p[1] >= ceil_z && p[0] > 0) p];
cap_profile = concat([[cap_run[0][0], ceil_z - 0.01]], cap_run, [[0, z_apex]]);

// The steepest overhang of a profile as printed, in degrees from vertical: where its radius
// shrinks going up.
function steepest(ps) = max([for (i = [0 : len(ps) - 2])
    let (dr = ps[i][0] - ps[i + 1][0], dz = ps[i + 1][1] - ps[i][1]) dz > 0 ? atan2(dr, dz) : (dr > 0 ? 90 : 0)]);

// The steepest lean of the cap's outside as printed: where its radius grows going up.
function cap_lean() = max([for (z = [0.5 : 0.5 : top_z - 1], j = [0 : 2 : flute_nt - 1])
    let (t = 360 * j / flute_nt) atan2(flute_r(z + 0.25, t) - flute_r(z - 0.25, t), 0.5)]);

module base_cavity() {
    rotate_extrude() polygon(concat([[0, z_floor]], base_profile, [[0, spigot_h + 1]]));
}

module cap_cavity() {
    rotate_extrude() polygon(concat([[0, ceil_z - 0.01]], cap_profile));
}

module hollow_base() {
    difference() {
        // As many sides as the cap's rings, so the two meet vertex for vertex at the seam.
        union() { shell(bottom_z, 0, $fn = flute_nt); spigot(); }
        base_cavity();
    }
}

// The Soma cap's bore, thread and lead-in, without its flat ceiling.
module hollow_cap() {
    d = thread_gap * sqrt(2);
    difference() {
        fluted_shell();
        translate([0, 0, -1]) cylinder(r = cap_bore, h = ceil_z + 1);
        intersection() {
            helix(cap_bore - 0.05, r_crest + thread_gap, half_base - thread_gap + 0.05 + d, half_crest + d, -2 * pitch,
                  ceil((ceil_z + 3 * pitch) / pitch));
            translate([0, 0, -1]) cylinder(r = r_crest + 2, h = ceil_z + 1);
        }
        translate([0, 0, -eps]) cylinder(r1 = r_crest + thread_gap + 0.6, r2 = cap_bore, h = 1.2);
        cap_cavity();
    }
}

if (mode == "egg") {
    hollow_base();
    hollow_cap();
    // The thread's play filled for viewing, as the Soma egg does.
    difference() {
        cylinder(r = r_crest + thread_gap + 0.7, h = ceil_z);
        translate([0, 0, -1]) cylinder(r = cap_bore - 0.5, h = ceil_z + 2);
    }
}
else if (mode == "base") hollow_base();
else if (mode == "cap") hollow_cap();
else if (mode == "thread") intersection() { hollow_base(); translate([0, 0, 0.05]) hollow_cap(); }
else if (mode == "walls") {
    echo(cavity_d = 2 * r_bore);
    echo(cavity_h = z_apex - z_floor);
    echo(min_wall = min(wall, floor_t, wall_min,
                        min([for (z = [0 : 0.2 : ceil_z]) chamfered(z) - flute_depth(z) - r_crest - thread_gap])));
    echo(overhang_margin = round((45 - max(steepest(base_profile), steepest(cap_profile))) * 1000) / 1000);
    echo(foot_margin = round((60 - atan(egg_slope(bottom_z))) * 1000) / 1000);
    echo(cap_lean_margin = round((45 - cap_lean()) * 1000) / 1000);
}
else assert(false, str("no mode ", mode));
