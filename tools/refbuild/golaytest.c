/* Dump the Golay code tables so the Python port can be byte-compared. */
#include "config.h"
#include <stdio.h>
#include <stdlib.h>
#include "outguess.h"
#include "golay.h"

int main(void)
{
	int i;
	init_golay();
	for (i = 0; i < 4096; i++)
		printf("E %ld\n", encoding_table[i]);
	for (i = 0; i < 2048; i++)
		printf("D %ld\n", decoding_table[i]);
	return 0;
}
