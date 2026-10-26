#!/bin/bash
set -eu

xml_source=$PWD
cd "$TV_XML_XZ_SOURCE"
./configure --host="$HOST" --prefix="$PREFIX" --disable-shared --with-pic
make -j "$CPU_COUNT"
make install

cd "$xml_source"
./configure --host="$HOST" --prefix="$PREFIX" --without-python --with-lzma="$PREFIX"
make -j "$CPU_COUNT"
make install

rm -r "$PREFIX"/{bin,share}
rm -r "$PREFIX"/lib/{*.a,*.la,*.sh}
