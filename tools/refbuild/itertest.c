/* Dump iterator positions so the Python port can be compared exactly. */
#include "config.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "outguess.h"
#include "arc.h"
#include "iterator.h"

int main(int argc, char **argv)
{
	bitmap bm;
	iterator it;
	int datalen, i, w;

	if (argc < 4) return 2;
	memset(&bm, 0, sizeof(bm));
	bm.bits = (size_t)atoi(argv[2]);
	datalen = atoi(argv[3]);

	iterator_init(&it, &bm, (u_char *)argv[1], (int)strlen(argv[1]));
	printf("O %d\n", (int)ITERATOR_CURRENT(&it));
	for (i = 0; i < 5 && datalen > 0; i++) {
		iterator_adapt(&it, &bm, datalen);
		printf("B %u", (unsigned)it.skipmod);
		for (w = 0; w < 8; w++) {
			printf(" %d", (int)ITERATOR_CURRENT(&it));
			iterator_next(&it, &bm);
		}
		printf("\n");
		datalen--;
	}
	return 0;
}
