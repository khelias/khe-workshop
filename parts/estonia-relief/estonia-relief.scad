// Estonia relief map: the land rises from a blue sea in one rounded outline that holds
// the islands to the mainland. Heights, outline, tiles and the places of the keys and
// keyholes come from data/, prepared from open data by data/prep.py (ADR-003).
// Each piece prints on its back; the keys and keyholes are cut into the back.

include <data/outline.scad>

mode = "tile";  // tile | small | key | coupon | seams | key_fit | key_snug | bed_margin
tile = 0;       // 0 north-west, 1 north-east, 2 south-west, 3 south-east

key_long = 30;       // across the seam
key_wide = 14;       // at its ends
key_waist = 7;
key_t = 2.4;         // the printed key
key_clear = 0.15;    // each side, between key and recess
recess_depth = 2.6;  // a little deeper than the key, for the glue

head_d = 9.5;        // a screw head passes here
shank_w = 4.6;       // the screw's shank slides up this slot
slot_long = 14;      // head centre to slot end
keyhole_lip = 1.8;   // material under the head, from the back

bed = 260;
bed_edge = 5.1;      // brim and its gap round every piece

$fn = 48;

module relief(file) scale([cell_mm, cell_mm, 0.01]) surface(file = file, convexity = 5);

module bowtie() polygon([[-key_long / 2, -key_wide / 2], [-key_long / 2, key_wide / 2], [0, key_waist / 2],
                         [key_long / 2, key_wide / 2], [key_long / 2, -key_wide / 2], [0, -key_waist / 2]]);

module recess() translate([0, 0, -1]) linear_extrude(recess_depth + 1) offset(delta = key_clear) bowtie();

// a keyhole at its head centre; the slot runs up, so the piece hangs from the slot's end
module keyhole(depth, lip = keyhole_lip) {
    translate([0, 0, -1]) {
        cylinder(d = head_d, h = depth + 1);
        translate([-shank_w / 2, 0, 0]) cube([shank_w, slot_long, lip + 1]);
        translate([0, 0, lip + 1]) hull() {
            cylinder(d = head_d, h = depth - lip);
            translate([0, slot_long, 0]) cylinder(d = head_d, h = depth - lip);
        }
    }
}

module keyholes(at, depth, lip = keyhole_lip) for (k = at) translate([k[0], k[1], 0]) keyhole(depth, lip);

module back_cuts() {
    for (k = keys) translate([k[0], k[1], 0]) rotate(k[2]) recess();
    keyholes(keyholes, 3.6);
}

module outline_prism(h = 60) linear_extrude(h) polygon(outline);

// tile i in the map's frame
module tile_body(i) intersection() {
    translate([tiles[i][0], tiles[i][1], 0]) relief(str("data/tile-", i, ".dat"));
    outline_prism();
}
module tile_piece(i) difference() { tile_body(i); back_cuts(); }

// the small map in its own frame: half the large map's cell centres, less a quarter cell
module small_piece() difference() {
    intersection() {
        relief("data/small.dat");
        linear_extrude(60) scale(1 / small_factor) translate([-cell_mm / 2, -cell_mm / 2]) polygon(outline);
    }
    keyholes(small_keyholes, 2.4, 1.2);  // a lighter piece on a thinner base
}

// two blocks that meet at x = 0 with a recess across the seam and a keyhole in one
module coupon_half(side) difference() {
    translate([side < 0 ? -40 : 0, -22.5, 0]) cube([40, 45, base_mm]);
    recess();
    if (side < 0) translate([-22, -12, 0]) keyhole(3.6);
}

module coupon() union() { coupon_half(-1); coupon_half(1); }

module key() linear_extrude(key_t) bowtie();

// a strip eps wide on each side of a seam; neither side may stand more than 0.01 mm over the
// other, up or along the seam, where a slanted edge moves by its slope times eps
eps = 0.0005;
tol = 0.01;
module seam_strip(i, axis, at, side) {
    intersection() {
        tile_body(i);
        if (axis == "x") translate([side < 0 ? at - eps : at, -1, -1]) cube([eps, 1000, 100]);
        else translate([-1, side < 0 ? at - eps : at, -1]) cube([1000, eps, 100]);
    }
}
module shifted(axis, d) translate(axis == "x" ? [d, 0, 0] : [0, d, 0]) children();
module widened(axis) for (u = [-tol, 0, tol], w = [0, tol])
    translate(axis == "x" ? [0, u, w] : [u, 0, w]) children();
// the middle half of the strip, so the body taken away never shares a face with it
module middle(axis, at) intersection() {
    children();
    if (axis == "x") translate([at + eps / 4, -1, -1]) cube([eps / 2, 1000, 100]);
    else translate([-1, at + eps / 4, -1]) cube([1000, eps / 2, 100]);
}
module over(axis, a, b, at) difference() {
    middle(axis, at) shifted(axis, eps) seam_strip(a, axis, at, -1);
    widened(axis) seam_strip(b, axis, at, 1);
}
module under(axis, a, b, at) difference() {
    middle(axis, at) seam_strip(b, axis, at, 1);
    shifted(axis, eps) widened(axis) seam_strip(a, axis, at, -1);
}
module seam_pair(axis, a, b, at) { over(axis, a, b, at); under(axis, a, b, at); }

if (mode == "tile") translate([-tiles[tile][0], -tiles[tile][1], 0]) tile_piece(tile);
else if (mode == "small") small_piece();
else if (mode == "key") key();
else if (mode == "coupon") { translate([-3, 0, 0]) coupon_half(-1); translate([3, 0, 0]) coupon_half(1); }
else if (mode == "seams") {
    seam_pair("x", 0, 1, tiles[0][2]);
    seam_pair("x", 2, 3, tiles[2][2]);
    seam_pair("y", 2, 0, tiles[2][3]);
    seam_pair("y", 3, 1, tiles[3][3]);
}
else if (mode == "key_fit") intersection() { coupon(); key(); }
else if (mode == "key_snug") intersection() {
    coupon();
    linear_extrude(key_t) offset(delta = key_clear + 0.05) bowtie();
}
else if (mode == "bed_margin") {
    xs = [for (p = outline) p[0]];
    ys = [for (p = outline) p[1]];
    small = max(max(xs) - min(xs), max(ys) - min(ys)) / small_factor;
    sizes = concat([for (t = tiles) max(t[2] - t[0], t[3] - t[1])], [small]);
    echo(bed_margin = bed - 2 * bed_edge - max(sizes));
}
