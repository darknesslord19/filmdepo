# TavsiyeFilmTest — CloudStream CS3 eğitim örneği

Bu proje CloudStream provider geliştirme mantığını öğretmek için hazırlanmıştır.

## İçerik
- Ana sayfa/kategori listeleme
- Arama
- Film/dizi detay bilgileri
- Poster, açıklama, yıl, kategori ve puan çıkarma
- `loadLinks()` kasıtlı olarak boş: üçüncü taraf yayın bağlantısı çıkarmaz.

## Derleme
Güncel CloudStream plugin template/repo yapısında Java 17 ve Gradle/Android Studio kullanılması önerilir.

Örnek:
```bash
./gradlew TavsiyeFilmTest:make
```

Windows:
```bat
gradlew.bat TavsiyeFilmTest:make
```

## Önemli
Site HTML'i değişirse CSS selector'ları güncellemek gerekir. Bu proje gerçek bir yayın oynatıcı eklentisi değil, katalog/arama/detay öğrenme örneğidir.
