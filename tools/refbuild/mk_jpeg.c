/* Re-encode a PPM as JPEG with explicit chroma sampling factors.
 *
 *   mk_jpeg <in.ppm> <out.jpg> <quality> <h_samp> <v_samp>
 *
 * Used to build 4:4:4 (1x1) and 4:2:2 (2x1) test carriers, which the
 * OutGuess compressor never produces itself (it always uses 2x2).
 */
#include <stdio.h>
#include <stdlib.h>
#include "jpeglib.h"

static unsigned char *read_ppm(const char *name, int *w, int *h)
{
	FILE *f = fopen(name, "rb");
	int maxval, c;
	unsigned char *buf;

	if (!f) { perror(name); exit(1); }
	if (fscanf(f, "P6 %d %d %d", w, h, &maxval) != 3) {
		fprintf(stderr, "bad header\n");
		exit(1);
	}
	fgetc(f);			/* single whitespace after maxval */
	buf = malloc((size_t)*w * *h * 3);
	if (!buf) exit(1);
	if (fread(buf, 3, (size_t)*w * *h, f) != (size_t)*w * *h) {
		fprintf(stderr, "short read\n");
		exit(1);
	}
	c = 0;
	(void)c;
	fclose(f);
	return buf;
}

int main(int argc, char *argv[])
{
	struct jpeg_compress_struct cinfo;
	struct jpeg_error_mgr jerr;
	JSAMPROW row;
	unsigned char *img;
	int w, h, hs, vs;

	if (argc != 6) {
		fprintf(stderr, "usage: %s <in.ppm> <out.jpg> <quality> <hsamp> <vsamp>\n",
			argv[0]);
		return 1;
	}
	img = read_ppm(argv[1], &w, &h);
	cinfo.err = jpeg_std_error(&jerr);
	jpeg_create_compress(&cinfo);

	FILE *f = fopen(argv[2], "wb");
	jpeg_stdio_dest(&cinfo, f);
	cinfo.image_width = (JDIMENSION)w;
	cinfo.image_height = (JDIMENSION)h;
	cinfo.input_components = 3;
	cinfo.in_color_space = JCS_RGB;
	jpeg_set_defaults(&cinfo);
	hs = atoi(argv[4]);
	vs = atoi(argv[5]);
	cinfo.comp_info[0].h_samp_factor = hs;
	cinfo.comp_info[0].v_samp_factor = vs;
	cinfo.comp_info[1].h_samp_factor = 1;
	cinfo.comp_info[1].v_samp_factor = 1;
	cinfo.comp_info[2].h_samp_factor = 1;
	cinfo.comp_info[2].v_samp_factor = 1;
	jpeg_set_quality(&cinfo, atoi(argv[3]), TRUE);

	jpeg_start_compress(&cinfo, TRUE);
	while (cinfo.next_scanline < cinfo.image_height) {
		row = img + (size_t)cinfo.next_scanline * w * 3;
		jpeg_write_scanlines(&cinfo, &row, 1);
	}
	jpeg_finish_compress(&cinfo);
	fclose(f);
	jpeg_destroy_compress(&cinfo);
	free(img);
	return 0;
}
