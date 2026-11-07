/* Encode a P6 PPM as a single-component (greyscale) JPEG.
 *
 *   mk_jpeg_gray <in.ppm> <out.jpg> <quality>
 *
 * Luminance uses the plain IJG RGB->Y integer transform, so the result is
 * comparable with what a colour JPEG carries in its Y channel.
 */
#include <stdio.h>
#include <stdlib.h>
#include "jpeglib.h"

int main(int argc, char *argv[])
{
	struct jpeg_compress_struct cinfo;
	struct jpeg_error_mgr jerr;
	JSAMPROW row;
	unsigned char *img, *grey;
	FILE *f;
	int w, h, maxval, i;

	if (argc != 4) {
		fprintf(stderr, "usage: %s <in.ppm> <out.jpg> <quality>\n", argv[0]);
		return 1;
	}
	f = fopen(argv[1], "rb");
	if (!f) { perror(argv[1]); return 1; }
	if (fscanf(f, "P6 %d %d %d", &w, &h, &maxval) != 3) {
		fprintf(stderr, "bad header\n");
		return 1;
	}
	fgetc(f);
	img = malloc((size_t)w * h * 3);
	grey = malloc((size_t)w * h);
	if (!img || !grey) return 1;
	if (fread(img, 3, (size_t)w * h, f) != (size_t)w * h) {
		fprintf(stderr, "short read\n");
		return 1;
	}
	fclose(f);
	for (i = 0; i < w * h; i++)
		grey[i] = (unsigned char) ((img[3 * i] * 19595
					   + img[3 * i + 1] * 38470
					   + img[3 * i + 2] * 7471 + 32768) >> 16);

	cinfo.err = jpeg_std_error(&jerr);
	jpeg_create_compress(&cinfo);
	f = fopen(argv[2], "wb");
	if (!f) { perror(argv[2]); return 1; }
	jpeg_stdio_dest(&cinfo, f);
	cinfo.image_width = (JDIMENSION) w;
	cinfo.image_height = (JDIMENSION) h;
	cinfo.input_components = 1;
	cinfo.in_color_space = JCS_GRAYSCALE;
	jpeg_set_defaults(&cinfo);
	jpeg_set_quality(&cinfo, atoi(argv[3]), TRUE);
	jpeg_start_compress(&cinfo, TRUE);
	while (cinfo.next_scanline < cinfo.image_height) {
		row = grey + (size_t) cinfo.next_scanline * w;
		jpeg_write_scanlines(&cinfo, &row, 1);
	}
	jpeg_finish_compress(&cinfo);
	fclose(f);
	jpeg_destroy_compress(&cinfo);
	free(img);
	free(grey);
	return 0;
}
