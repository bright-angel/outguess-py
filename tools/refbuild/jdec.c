/* Debug helper: decode a JPEG with the original libjpeg path and dump raw RGB. */
#include "config.h"
#include <stdio.h>
#include <stdlib.h>
#include "outguess.h"
#include "pnm.h"

int steg_foil, steg_foilfail, steg_stat;

void *checkedmalloc(size_t n)
{
  void *p = malloc(n);
  if (!p) { fprintf(stderr, "checkedmalloc: not enough memory\n"); exit(1); }
  return p;
}

image *read_JPEG_file (FILE *infile);

int main(int argc, char **argv)
{
  FILE *in, *out;
  image *img;
  size_t n;
  if (argc < 3) { fprintf(stderr, "usage: jdec in.jpg out.raw\n"); return 2; }
  in = fopen(argv[1], "rb");
  if (!in) { perror("fopen"); return 1; }
  img = read_JPEG_file(in);
  fclose(in);
  n = (size_t)img->x * img->y * img->depth;
  out = fopen(argv[2], "wb");
  fwrite(&img->x, sizeof(int), 1, out);
  fwrite(&img->y, sizeof(int), 1, out);
  fwrite(&img->depth, sizeof(int), 1, out);
  fwrite(img->img, 1, n, out);
  fclose(out);
  fprintf(stderr, "jdec: %dx%d depth %d\n", img->x, img->y, img->depth);
  return 0;
}
