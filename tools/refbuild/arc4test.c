/* Dump ARC4 keystream so the Python port can be compared bit for bit. */
#include "config.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "outguess.h"
#include "arc.h"

int main(int argc, char **argv)
{
	struct arc4_stream as;
	int i;
	u_char seed[2];

	if (argc < 2) return 2;
	arc4_initkey(&as, "Seeding", (u_char *)argv[1], (int)strlen(argv[1]));
	for (i = 0; i < 16; i++)
		printf("W %u\n", (unsigned)arc4_getword(&as));

	seed[0] = (u_char)atoi(argc > 2 ? argv[2] : "7");
	seed[1] = 0;
	arc4_addrandom(&as, seed, 2);
	for (i = 0; i < 8; i++)
		printf("S %u\n", (unsigned)arc4_getword(&as));

	for (i = 0; i < 8; i++)
		printf("B %u\n", (unsigned)arc4_getbyte(&as));
	return 0;
}
