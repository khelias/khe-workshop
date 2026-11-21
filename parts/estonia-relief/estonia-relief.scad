// Estonia relief map: the land rises from a blue sea in one rounded outline that holds
// the islands to the mainland. Heights, outline, tiles and the places of the keys and
// keyholes come from data/, prepared from open data by data/prep.py (ADR-003).
// Each piece prints on its back; the keys and keyholes are cut into the back.

include <data/outline.scad>
use <../../fonts/FamiljenGrotesk-SemiBold.ttf>

mode = "tile";  // tile | small | key | coupon | seams | key_fit | key_snug | bed_margin | label_fits | label_long
tile = 0;       // 0 north-west, 1 north-east, 2 south-west, 3 south-east
grid = cell_mm; // the print's grid; the exports take cell_mm * coarse, every second cell, for their budget
assert(grid == cell_mm || grid == cell_mm * coarse, "grid is cell_mm or cell_mm * coarse");

// A label each maker chooses, cut down to the black bottom layer under the blue sea and white land:
// "coast" runs it along an arc of sea grown in the Gulf of Finland, "place" puts a dot at a place
// with the name beside it. Print it black to 0.8 mm under the sea's top, then blue, then white.
label = "";
label_style = "coast";         // coast | place; a label of your own is checked with mode="label_fits"
place = [58.885, 25.557];      // latitude, longitude (Paide)
label_side = "upper right";    // upper right | upper left | lower right | lower left of the dot
label_font = "Familjen Grotesk:style=SemiBold";
label_depth = 0.8;             // the label's floor under the sea's top
coast_cap = [8.8, 14];         // smallest and largest capital height on the large map; half on the small
place_cap = 10.8;
dot_d = 4.6;

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

// a height grid by its name in data/, at the chosen grid
module relief(name) scale([grid, grid, 0.01])
    surface(file = str("data/", name, grid == cell_mm ? "" : "-coarse", ".dat"), convexity = 5);

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

labelled = label != "";
shape = labelled && label_style == "coast" ? outline_coast : outline;

module outline_prism(h = 60) linear_extrude(h) polygon(shape);

// --- the label, in the large map's frame ---

assert(!labelled || (let(f = fontmetrics(font = label_font).font) f.family == "Familjen Grotesk"
       && f.style == "SemiBold"), "the label font did not load");

// EPSG:3301 (L-EST97): Lambert conformal conic on GRS80
function lcc_m(p) = cos(p) / sqrt(1 - lcc_e2 * sin(p) ^ 2);
function lcc_t(p) = tan(45 - p / 2) / ((1 - sqrt(lcc_e2) * sin(p)) / (1 + sqrt(lcc_e2) * sin(p))) ^ (sqrt(lcc_e2) / 2);
lcc_a = 6378137;
lcc_e2 = 2 / 298.257222101 - 1 / 298.257222101 ^ 2;
lcc_p1 = 59 + 20 / 60;
lcc_p2 = 58;
lcc_p0 = 57 + 31 / 60 + 3.19415 / 3600;
lcc_n = (ln(lcc_m(lcc_p1)) - ln(lcc_m(lcc_p2))) / (ln(lcc_t(lcc_p1)) - ln(lcc_t(lcc_p2)));
lcc_f = lcc_m(lcc_p1) / (lcc_n * lcc_t(lcc_p1) ^ lcc_n);
function lcc_rho(p) = lcc_a * lcc_f * lcc_t(p) ^ lcc_n;
function lest(lat, lon) = [500000 + lcc_rho(lat) * sin(lcc_n * (lon - 24)),
                           6375000 + lcc_rho(lcc_p0) - lcc_rho(lat) * cos(lcc_n * (lon - 24))];
function map_mm(lat, lon) = (lest(lat, lon) - lest_origin_m) * 1000 / map_scale;
for (q = lest_points) assert(norm(map_mm(q[0], q[1]) - [q[2], q[3]]) < 0.05, "the projection is off");

// capitals: a-z and Latin-1 by their offset, Š and Ž one below their small letters
function upper(s) = chr([for (c = s) let(o = ord(c))
    (o >= 97 && o <= 122) || (o >= 224 && o <= 254 && o != 247) ? o - 32 : o == 353 || o == 382 ? o - 1 : o]);

cap_ratio = textmetrics("H", size = 10, font = label_font).size[1] / 10;  // capital height per text size
function adv(c, size) = textmetrics(c, size = size, font = label_font).advance[0];
function sum_to(v, i) = i <= 0 ? 0 : v[i - 1] + sum_to(v, i - 1);
coast_usable = 2 * coast_arc[4] - 8;
function coast_track(t) = len(t) <= 8 ? 0.22 : 0.1;  // letter spacing, in text sizes
// a text's length along the arc at text size 1; the capitals take the largest size that fits
function coast_len1(t) = sum_to([for (c = t) adv(c, 1)], len(t)) + coast_track(t) * (len(t) - 1);
function coast_size(t) = min(coast_cap[1] / cap_ratio, coast_usable / max(coast_len1(t), 0.01));
coast_text = upper(label);
long_sample = upper("Tallinn 21.11.2026");  // the longest label the checks try
assert(label_style == "coast" || label_style == "place", "label_style is coast or place");
coast_cap_mm = coast_size(coast_text) * cap_ratio;
assert(!labelled || label_style != "coast" || coast_cap_mm >= coast_cap[0] - 1e-6,
       str("the label is too long for the coast: capitals of ", coast_cap_mm, " mm"));

module coast_label(t = coast_text) {
    size = coast_size(t);
    a = [for (c = t) adv(c, size)];
    gap = coast_track(t) * size;
    total = sum_to(a, len(a)) + gap * (len(a) - 1);
    r = coast_arc[2];
    for (i = [0 : len(a) - 1]) let(s = sum_to(a, i) + gap * i + a[i] / 2 - total / 2,
                                   ang = coast_arc[3] - s / r * 180 / PI)
        translate([coast_arc[0] + r * cos(ang), coast_arc[1] + r * sin(ang)]) rotate(ang - 90)
            text(t[i], size = size, font = label_font, halign = "center");
}

module place_label() {
    p = map_mm(place[0], place[1]);
    size = place_cap / cap_ratio;
    gap = dot_d / 2 + 0.25 * place_cap;
    left = label_side == "upper left" || label_side == "lower left";
    lower = label_side == "lower right" || label_side == "lower left";
    assert(left || lower || label_side == "upper right", "label_side is upper or lower, right or left");
    translate(p) {
        circle(d = dot_d);
        translate([left ? -gap : gap, lower ? -0.3 * place_cap : 0.3 * place_cap])
            text(label, size = size, font = label_font, halign = left ? "right" : "left",
                 valign = lower ? "top" : "baseline");
    }
}

module label_2d() if (labelled) { if (label_style == "place") place_label(); else if (label_style == "coast") coast_label(); }
module in_small_frame() scale(1 / small_factor) translate([-cell_mm / 2, -cell_mm / 2]) children();
module label_cut(floor) translate([0, 0, floor]) linear_extrude(60) children();


// tile i in the map's frame
module tile_body(i) intersection() {
    translate([tiles[i][0], tiles[i][1], 0]) relief(str("tile-", i));
    outline_prism();
}
module tile_piece(i) difference() { tile_body(i); back_cuts(); label_cut(base_mm - label_depth) label_2d(); }

module small_keyhole_cuts() keyholes(small_keyholes, 2.4, 1.2);  // a lighter piece on a thinner base

// the small map in its own frame: half the large map's cell centres, less a quarter cell
module small_piece() difference() {
    intersection() {
        relief("small");
        linear_extrude(60) in_small_frame() polygon(shape);
    }
    small_keyhole_cuts();
    label_cut(small_base_mm - label_depth) in_small_frame() label_2d();
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
    xs = [for (p = shape) p[0]];
    ys = [for (p = shape) p[1]];
    small = max(max(xs) - min(xs), max(ys) - min(ys)) / small_factor;
    sizes = concat([for (t = tiles) max(t[2] - t[0], t[3] - t[1])], [small]);
    echo(bed_margin = bed - 2 * bed_edge - max(sizes));
}
// on the small map: a coast label, and the longest one, must not touch land, a place label must lie
// on land, and neither may reach a keyhole, whose pocket rises above the label's floor
else if (mode == "label_fits") { if (labelled) {
    if (label_style == "coast") intersection() {
        relief("small");
        label_cut(small_base_mm + 0.3) in_small_frame() { coast_label(); coast_label(long_sample); }
    }
    else difference() {
        translate([0, 0, small_base_mm + 0.1]) linear_extrude(0.2) in_small_frame() label_2d();
        relief("small");
    }
    intersection() {
        small_keyhole_cuts();
        label_cut(small_base_mm - label_depth) in_small_frame() label_2d();
    }
} }
else if (mode == "label_long") echo(label_long_cap = coast_size(long_sample) * cap_ratio / small_factor);
