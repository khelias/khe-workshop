// Soma egg: a screw-top egg that closes only when the seven Soma pieces
// inside are packed back into a 3 x 3 x 3 cube. The pocket is exactly one
// cube deep, so any wrong packing stands at least a cube above the rim.

/* Pieces */
u = 10;            // cube edge
g = 0.1;           // inset per face, so neighbouring pieces have 0.2 between them

/* Pocket */
pocket_gap = 0.25; // per side, cube to pocket wall
ceil_gap = 0.8;    // spigot top to the cap's ceiling; covers the ceiling bridge's sag

/* Egg: Hügelschäffer curve, blunt end down. The breadth has to hold the
   cube's diagonal a full cube deep below the thread, which sets the size. */
egg_b = 58;
egg_l = 76.5;      // length of the uncut curve
egg_w = 4.5;       // shift of the breadth toward the blunt end
egg_zc = -3;       // curve centre relative to the seam
bottom_z = -37.6;  // flat foot, where the overhang reaches 60 degrees
seam_chamfer = 0.5;

/* Thread on the spigot */
spigot_h = 8;
pitch = 4;
thread_depth = 1.4;
thread_gap = 0.3;  // normal to the flanks and radial
wall_min = 1.6;    // pocket corner to the thread core

/* Ribs crossing over the shell. Raised, because where two grooves cross
   the corner above the crossing would start printing in the air. */
pattern = "lattice";   // or "none"
rib_h = 0.6;
rib_w = 1.6;
rib_n = 16;
rib_twist = 80;        // steep enough that no rib's underside prints as an overhang
rib_from = -18;        // below this the shell leans out too far
rib_to = 30;           // above this the ribs crowd together toward the tip
rib_slices = 120;

mode = "assembly";
lift = 0;          // probe: raise one piece of the solved cube
explode = 22;      // assembly view: cap above the seam
piece = 0;         // solved_piece: which piece of the solution, 0 to 6

$fn = 128;
eps = 0.01;

a = 3 * u / 2 + pocket_gap;               // pocket half width
r_core = a * sqrt(2) + wall_min;          // spigot thread core
r_crest = r_core + thread_depth;
pocket_floor = spigot_h - 3 * u;
ceil_z = spigot_h + ceil_gap;
top_z = egg_l / 2 + egg_zc;
steps = 160;

// Each piece in its printing orientation: every cell rests on the bed or on another cell.
pieces = [
    ["V", [[0,0,0],[1,0,0],[0,1,0]]],
    ["L", [[0,0,0],[1,0,0],[2,0,0],[0,1,0]]],
    ["T", [[0,0,0],[1,0,0],[2,0,0],[1,1,0]]],
    ["Z", [[0,0,0],[1,0,0],[1,1,0],[2,1,0]]],
    ["A", [[0,0,0],[1,0,0],[0,1,0],[0,1,1]]],
    ["B", [[0,0,0],[1,0,0],[0,1,0],[1,0,1]]],
    ["P", [[0,0,0],[1,0,0],[0,1,0],[0,0,1]]]
];

// One of the 11520 packings (240 up to rotation and reflection), cell (0,0,0)
// at the pocket's -x -y corner on its floor.
solution = [
    ["V", [[0,0,2],[1,0,2],[1,1,2]]],
    ["L", [[0,1,2],[0,2,0],[0,2,1],[0,2,2]]],
    ["T", [[1,0,1],[2,0,0],[2,0,1],[2,0,2]]],
    ["Z", [[0,0,0],[1,0,0],[1,1,0],[2,1,0]]],
    ["A", [[1,2,1],[1,2,2],[2,1,2],[2,2,2]]],
    ["B", [[1,2,0],[2,1,1],[2,2,0],[2,2,1]]],
    ["P", [[0,0,1],[0,1,0],[0,1,1],[1,1,1]]]
];

colours = ["#e23a2e", "#f5f3ee", "#e23a2e", "#f5f3ee", "#e23a2e", "#f5f3ee", "#e23a2e"];

function adjacent(p, q) = abs(p[0] - q[0]) + abs(p[1] - q[1]) + abs(p[2] - q[2]) == 1;

module piece(cells) {
    for (c = cells) translate(c * u + [g, g, g]) cube(u - 2 * g);
    for (i = [0 : len(cells) - 1], j = [0 : len(cells) - 1])
        if (i < j && adjacent(cells[i], cells[j]))
            hull() for (c = [cells[i], cells[j]])
                translate(c * u + [u / 2, u / 2, u / 2]) cube(u - 2 * g, center = true);
}

module solved(raise = 0) {
    for (i = [0 : len(solution) - 1])
        translate([-3 * u / 2, -3 * u / 2, pocket_floor + (i == 2 ? raise : 0)])
            color(colours[i]) piece(solution[i][1]);
}

function egg_r(z) = let (x = z - egg_zc)
    egg_b / 2 * sqrt(max(0, (egg_l * egg_l - 4 * x * x) / (egg_l * egg_l + 8 * egg_w * x + 4 * egg_w * egg_w)));

function chamfered(z) = egg_r(z) - max(0, seam_chamfer - abs(z));

module shell(z0, z1) {
    zs = [for (i = [0 : steps]) z0 + (z1 - z0) * i / steps];
    rotate_extrude() polygon(concat([[0, z0]], [for (z = zs) [chamfered(z), z]], [[0, z1]]));
}

// Helical ridge with a trapezoid section: half widths hw_in at r_in and
// hw_out at r_out, from z = z0 for the given number of turns.
module helix(r_in, r_out, hw_in, hw_out, z0, turns, seg = 96) {
    n = turns * seg;
    prof = [[r_in, -hw_in], [r_out, -hw_out], [r_out, hw_out], [r_in, hw_in]];
    pts = [for (i = [0 : n]) let (t = 360 * i / seg, z = z0 + pitch * i / seg)
        for (p = prof) [p[0] * cos(t), p[0] * sin(t), z + p[1]]];
    sides = [for (i = [0 : n - 1], k = [0 : 3])
        let (a0 = i * 4 + k, a1 = i * 4 + (k + 1) % 4)
            [a0, a1, a1 + 4, a0 + 4]];
    polyhedron(pts, concat([[3, 2, 1, 0]], sides, [[n * 4, n * 4 + 1, n * 4 + 2, n * 4 + 3]]));
}

half_base = pitch / 4 + thread_depth / 2;   // 45 degree flanks
half_crest = pitch / 4 - thread_depth / 2;

module spigot() {
    rotate_extrude() polygon([[0, -eps], [r_core, -eps], [r_core, spigot_h - 0.5],
                              [r_core - 0.5, spigot_h], [0, spigot_h]]);
    intersection() {
        helix(r_core - 0.2, r_crest, half_base, half_crest, -pitch, ceil((spigot_h + 2 * pitch) / pitch));
        rotate_extrude() polygon([[0, 0], [r_crest + 1, 0], [r_crest + 1, spigot_h - 2.2],
                                  [r_core - 0.1, spigot_h - 0.6], [0, spigot_h - 0.6]]);
    }
}

// Rib height ramps at 45 degrees at both ends, so a rib's lower end rests on the shell.
function rib_height(z) = max(0, min(rib_h, z - rib_from, rib_to - z));

module band() {
    zs = [for (i = [0 : steps]) rib_from + (rib_to - rib_from) * i / steps];
    rotate_extrude() polygon(concat([for (z = zs) [chamfered(z) + rib_height(z), z]],
                                    [for (i = [steps : -1 : 0]) [egg_r(zs[i]) - 0.2, zs[i]]]));
}

module lattice() {
    for (dir = [-1, 1]) translate([0, 0, rib_from - 1])
        linear_extrude(height = rib_to - rib_from + 2, twist = dir * rib_twist, slices = rib_slices)
            for (i = [0 : rib_n - 1]) rotate(i * 360 / rib_n)
                translate([0, -rib_w / 2]) square([egg_b, rib_w]);
}

module ribs(z0, z1) {
    if (pattern == "lattice") intersection() {
        band();
        lattice();
        translate([-egg_b, -egg_b, z0]) cube([2 * egg_b, 2 * egg_b, z1 - z0]);
    }
}

module base() {
    difference() {
        union() { shell(bottom_z, 0); spigot(); ribs(bottom_z, 0); }
        translate([-a, -a, pocket_floor]) cube([2 * a, 2 * a, 3 * u + 1]);
    }
}

module cap() {
    d = thread_gap * sqrt(2);
    difference() {
        union() { shell(top_z, 0); ribs(0, top_z); }
        translate([0, 0, -1]) cylinder(r = r_core + thread_gap, h = ceil_z + 1);
        intersection() {
            helix(r_core + thread_gap - 0.05, r_crest + thread_gap, half_base - thread_gap + 0.05 + d, half_crest + d, -2 * pitch,
                  ceil((ceil_z + 3 * pitch) / pitch));
            translate([0, 0, -1]) cylinder(r = r_crest + 2, h = ceil_z + 1);
        }
        translate([0, 0, -eps]) cylinder(r1 = r_crest + thread_gap + 0.6, r2 = r_core + thread_gap, h = 1.2);
    }
}

module pieces_plate() {
    for (i = [0 : len(pieces) - 1])
        translate([(i % 4) * 4 * u, floor(i / 4) * 3.5 * u, 0]) piece(pieces[i][1]);
}

// The fit test keeps only the thread, the pocket and the cap's ceiling.
test_r = r_crest + thread_gap + 2.4;

// The closed egg for viewing; the thread's play is filled, so its gaps do not read as a print.
if (mode == "egg") {
    base();
    cap();
    difference() {
        cylinder(r = r_crest + thread_gap + 0.7, h = ceil_z);
        translate([0, 0, -1]) cylinder(r = r_core - 0.5, h = ceil_z + 2);
    }
}
else if (mode == "base") base();
else if (mode == "cap") cap();
else if (mode == "pieces") pieces_plate();
else if (mode == "test_base") intersection() { base(); translate([0, 0, -2]) cylinder(r = test_r, h = spigot_h + 2); }
else if (mode == "test_cap") intersection() { cap(); cylinder(r = test_r, h = ceil_z + 1.6); }
else if (mode == "test_piece") piece(pieces[1][1]);
else if (mode == "solved_piece") translate([-3 * u / 2, -3 * u / 2, pocket_floor]) piece(solution[piece][1]);
else if (mode == "closed") intersection() { union() { base(); cap(); } solved(); }
else if (mode == "raised") intersection() { cap(); solved(lift); }
else if (mode == "thread") intersection() { base(); translate([0, 0, 0.05]) cap(); }
else if (mode == "walls") {
    echo(corner_wall = r_core - a * sqrt(2));
    echo(bore_wall = egg_r(ceil_z) - r_crest - thread_gap);
    echo(side_gap = a - (3 * u / 2 - g));
}
else {
    base();
    translate([0, 0, explode]) cap();
    solved();
}
