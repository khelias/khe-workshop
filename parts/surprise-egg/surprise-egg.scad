// Surprise egg: the Soma egg's shell, thread and ribs, hollow inside for a small
// toy. The cavity is the egg's own outline set in by one wall, so every wall is
// as thin as the shell, and it never overhangs more than 45 degrees as printed:
// the base stands upright, the cap stands on its rim with the tip up.

include <../soma-egg/soma-egg.scad>

// The Soma egg draws nothing of its own here; every mode is drawn below.
library = true;

wall = 1.6;        // shell thickness along its normal
floor_t = 2;       // the base's floor
mode = "egg";

r_bore = r_core - wall_min;                // the opening through the spigot
cap_bore = r_core + thread_gap;            // the cap's bore, as the Soma cap's
z_floor = bottom_z + floor_t;
z_apex = top_z - wall;                     // the cavity's tip, under the shell's
cavity_steps = 120;

// The slope of the egg's outline, dr/dz.
function egg_slope(z) = (egg_r(z + 0.01) - egg_r(z - 0.01)) / 0.02;

// A point of the outline moved inward by the wall along its normal.
function inset(z) = let (d = egg_slope(z), l = sqrt(1 + d * d)) [egg_r(z) - wall / l, z + wall * d / l];

// The inset outline from z0 to z1, each point held inside the limit r <= f(z).
function inset_run(z0, z1, limit) = [for (i = [0 : cavity_steps]) let (p = inset(z0 + (z1 - z0) * i / cavity_steps))
    [min(p[0], limit(p[1])), p[1]]];

// The base: the inset bowl from its floor up, narrowing at 45 degrees into the bore.
base_run = [for (p = inset_run(bottom_z, 0, function(z) r_bore - z)) if (p[1] >= z_floor && p[1] <= 0) p];
base_profile = concat([[base_run[0][0], z_floor]], base_run, [[r_bore, 0], [r_bore, spigot_h + 1]]);

// The cap: the inset dome from the top of the bore to the tip, closing at 45 degrees.
cap_run = [for (p = inset_run(ceil_z - 2 * wall, top_z, function(z) z_apex - z)) if (p[1] >= ceil_z && p[0] > 0) p];
cap_profile = concat([[cap_run[0][0], ceil_z - 0.01]], cap_run, [[0, z_apex]]);

// The steepest overhang of a profile as printed, in degrees from vertical: where its radius
// shrinks going up.
function steepest(ps) = max([for (i = [0 : len(ps) - 2])
    let (dr = ps[i][0] - ps[i + 1][0], dz = ps[i + 1][1] - ps[i][1]) dz > 0 ? atan2(dr, dz) : (dr > 0 ? 90 : 0)]);

module base_cavity() {
    rotate_extrude() polygon(concat([[0, z_floor]], base_profile, [[0, spigot_h + 1]]));
}

module cap_cavity() {
    rotate_extrude() polygon(concat([[0, ceil_z - 0.01]], cap_profile));
}

module hollow_base() {
    difference() {
        union() { shell(bottom_z, 0); spigot(); ribs(bottom_z, 0); }
        base_cavity();
    }
}

// The Soma cap's bore, thread and lead-in, without its flat ceiling.
module hollow_cap() {
    d = thread_gap * sqrt(2);
    difference() {
        union() { shell(top_z, 0); ribs(0, top_z); }
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
    echo(min_wall = min(wall, floor_t, wall_min, egg_r(ceil_z) - r_crest - thread_gap));
    echo(overhang_margin = round((45 - max(steepest(base_profile), steepest(cap_profile))) * 1000) / 1000);
}
else assert(false, str("no mode ", mode));
