// Licence: CC BY-NC 4.0. The twist-lock profile is measured from Printables model
// 789473 by Peter H, https://www.printables.com/model/789473, itself a remix of
// model 323661 by magu, https://www.printables.com/model/323661. Both are CC BY-NC 4.0.
//
// U6-LR holder that plugs into a Schuko (CEE 7/3) socket. One printed part,
// no screws, no pins.
//
// - A plug body sized to the standard (GOST 7396.1-89 = IEC 83, sheets C2a
//   socket and C2b plug) fills the socket recess. The socket's own earth
//   clips press on its earth faces top and bottom and drop into a shallow
//   groove there, which is what keeps the holder from pulling out.
// - The U6-LR twist-lock is part of the same print. Its profile was measured
//   from Printables 789473, a printed plate known to fit, and rebuilt here
//   without that plate's screw holes.
// - The AP centre sits below the socket so the AP's rear LAN port is over the
//   open centre: the patch cable goes back through it and leaves sideways
//   behind the plate. A plug body behind the port would block the cable.
// - A pad lower down rests on the cover of the socket in the row below. It
//   takes the AP's tipping moment, so the earth clips only have to hold a few
//   newtons. Without a socket below, a foot can reach the wall instead.
//
// Modelled in print orientation: the AP-side face lies on the bed (z = 0),
// z grows towards the wall, +y is up on the wall.

/* [Socket: GOST 7396.1-89 / IEC 83 C2a, C2b] */
body_d      = 36.5;  // C2b plug body 36.5 +-0.5; C2a recess 39 +-1
body_l      = 15.5;  // C2b body length 15.5 min; C2a recess depth 17.5 +0.5
earth_face  = 32.4;  // across the earth faces, C2b 32 +0.5; clips rest at 29, may spread to 33
earth_seat  = 30.8;  // across the groove floor, the clips still press at 29
// Across the sides at the pin line, C2b 32 +-0.5. C2a puts the guide ribs
// 32.7-33.5 apart, so the flats ride on them and keep the plug square.
side_flat   = 32.2;
// Groove along the earth face, depth below the socket face. C2a puts the
// clip tips 2.5-4 mm below the face (recess 17.5..18 minus clip 14..15).
groove      = [1.0, 2.0, 4.5, 6.0]; // land ends, floor starts, floor ends, land again
lead_in     = 3;     // C2b leaves the first 3 mm of the earth face free
seat_h      = 3;     // ring that sits on the socket cover, keeps the plate off the frame rims
seat_r      = 26;

/* [Where the bottom rests] */
rest        = "socket"; // socket: pad on the cover of the socket below | wall: foot to the wall
// Socket centre to socket centre between the two frame rows, read off a
// photo: 85 mm frame plus a ~19 mm gap. The pad lands on the flat cover
// beside the recess, so this may be off by up to ~20 mm.
row_pitch   = 104;
pad_w       = 52;    // spans the recess (39), stays on the 55 mm cover
pad_h       = 12;
frame_proud = 10;    // rest = wall: socket cover face to wall
foot_gap    = 0.5;   // rest = wall: foot stops this short of the wall; the AP's weight closes it

/* [U6-LR twist-lock, measured from Printables 789473] */
bay_h       = 9.5;   // AP face to the plate behind it
r_in        = 30.7;  // open centre, room for the LAN plug
r_core      = 41.2;
r_tab       = 45;
flange_h    = 1.25;  // the AP's hooks sit behind this lip
bump_h      = 2.2;   // detent the hooks click over
// Angles as measured, repeated every 180 degrees.
flanges     = [[8.5, 51.25], [68.5, 171.25]];
stops       = [[8.5, 21.25], [68.5, 141.25]];
bumps       = [[37, 51.25, 38.25, 49], [157, 171.25, 158.25, 169]]; // base, top
bay_rot     = 0;     // turns the AP's resting angle, degrees

/* [Plate] */
ap_drop     = 57;    // AP centre below the socket centre: r_in + seat_r clears the open centre
plate_t     = 6;
hub_r       = 47;
strut_w     = 30;
foot_y      = -160;  // rest = wall: lower edge, inside the AP's outline (AP radius 110)
foot_h      = 8;
foot_w      = 50;
cable_w     = 9;     // slot from the open centre to the side, under the AP
cable_dir   = 0;     // print-frame angle: 0 = towards the left seen from the room

/* [Print] */
part        = "all"; // all | plug_test | lock_test

$fn = 120;

z_plate = bay_h;
z_cover = bay_h + plate_t + seat_h;  // socket cover face
ap_c    = [0, -ap_drop];
low_y   = rest == "socket" ? -row_pitch - pad_h / 2 : foot_y;  // lowest point of the plate

module annular_sector(r0, r1, a0, a1) {
    intersection() {
        difference() { circle(r1); circle(r0); }
        polygon([[0, 0], for (a = [a0 : (a1 - a0) / 24 : a1]) 2 * r1 * [cos(a), sin(a)]]);
    }
}

module slab(r0, r1, a0, a1, z0, z1) {
    translate([0, 0, z0]) linear_extrude(z1 - z0) annular_sector(r0, r1, a0, a1);
}

module twist_lock() {
    // The profile was measured with the opposite handedness; mirror back.
    rotate(bay_rot) mirror([0, 1, 0]) intersection() {
        union() {
            slab(r_in, r_core, 0, 360, 0, bay_h);
            for (k = [0, 180]) rotate(k) {
                for (f = flanges) {
                    // Small step at the face eases the hooks into the gaps.
                    slab(r_core - 1, r_tab, f[0] + 0.4, f[1] - 0.4, 0, 0.5);
                    slab(r_core - 1, r_tab, f[0], f[1], 0.5, flange_h);
                }
                // Up into the plate, filling the 45 degree cut above the pockets.
                for (s = stops) slab(r_core - 1, r_tab, s[0], s[1], 0.5, bay_h + r_tab - r_core);
                for (b = bumps) hull() {
                    slab(r_core - 1, r_tab, b[0], b[1], flange_h - 0.01, flange_h);
                    slab(r_core - 1, r_tab, b[2], b[3], bump_h - 0.01, bump_h);
                }
            }
        }
        // 0.5 mm chamfer on both edges of the AP-side face.
        rotate_extrude() polygon([[r_in + 0.5, 0], [r_tab - 0.5, 0], [r_tab, 0.5],
                                  [r_tab, bay_h + 4], [r_in, bay_h + 4], [r_in, 0.5]]);
    }
}

module plate() {
    difference() {
        translate([0, 0, z_plate]) linear_extrude(plate_t) difference() {
            union() {
                hull() { translate(ap_c) circle(hub_r); circle(seat_r); }
                translate([-strut_w / 2, low_y]) square([strut_w, -ap_drop - low_y]);
            }
            translate(ap_c) circle(r_in);
        }
        // 45 degree underside over the hook pockets so no support lands in them.
        translate(ap_c) rotate_extrude()
            polygon([[r_core, z_plate - 0.01], [r_tab, z_plate - 0.01], [r_tab, z_plate + r_tab - r_core]]);
    }
}

module foot() {
    if (rest == "socket")
        // Same height as the seat: both covers lie in one plane.
        translate([-pad_w / 2, low_y, z_plate]) cube([pad_w, pad_h, z_cover - z_plate]);
    else
        translate([-foot_w / 2, foot_y, z_plate])
            cube([foot_w, foot_h, z_cover - z_plate + frame_proud - foot_gap]);
}

// The patch cable leaves the open centre between the lock and the covers.
module cable_slot() {
    translate(ap_c) rotate(cable_dir) translate([0, -cable_w / 2, z_plate])
        cube([hub_r + 20, cable_w, z_cover]);
}

// Half-width of the plug at depth t below the socket face, top and bottom.
function earth_profile() = let(e = earth_face / 2, s = earth_seat / 2) [
    [e, 0], [e, groove[0]], [s, groove[1]], [s, groove[2]], [e, groove[3]],
    [e, body_l - lead_in], [s - 1.5, body_l]];

module plug() {
    translate([0, 0, z_cover - seat_h]) cylinder(r = seat_r, h = seat_h);
    translate([0, 0, z_cover]) intersection() {
        union() {
            cylinder(d = body_d, h = body_l - 1);
            translate([0, 0, body_l - 1]) cylinder(d1 = body_d, d2 = body_d - 2, h = 1);
        }
        // Flat sides clear the recess's guide ribs at the pin line.
        cube([side_flat, body_d + 2, 2 * body_l + 2], center = true);
        // Earth faces top and bottom: flat, grooved, with a lead-in at the tip.
        p = earth_profile();
        rotate([90, 0, 90]) linear_extrude(body_d + 2, center = true)
            polygon(concat([for (q = p) [q[0], q[1]]], [for (i = [len(p) - 1 : -1 : 0]) [-p[i][0], p[i][1]]]));
    }
}

assert(rest == "socket" || foot_y + foot_h < -(85 / 2), "foot must sit below a standard 85 mm frame");
assert(rest == "wall" || low_y + pad_h < -(85 / 2), "pad must sit on the row below");
assert(ap_drop >= r_in + seat_r, "seat would hang over the open centre");

if (part == "plug_test") {
    // Plug and seat only: checks the earth clips catch, about 20 minutes.
    translate([0, 0, -(z_cover - seat_h)]) plug();
} else if (part == "lock_test") {
    // Twist-lock with a thin back: checks the AP clicks on, about 30 minutes.
    translate(-ap_c) {
        translate(ap_c) twist_lock();
        translate([0, 0, z_plate]) linear_extrude(4) translate(ap_c)
            difference() { circle(hub_r); circle(r_in); }
    }
} else {
    difference() {
        union() {
            translate(ap_c) twist_lock();
            plate();
            foot();
            plug();
        }
        cable_slot();
    }
}
