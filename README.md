# TavsiyeFilmizle - CloudStream eklentisi (.cs3 projesi)

Bu klasor CloudStream'in resmi eklenti sablonuna gore hazirlandi. `.cs3` dosyasi Gradle ile derlenir.

## En kolay yol: GitHub Actions (kendi bilgisayarina bir sey kurmadan)
1. github.com'da ucretsiz hesap ac, yeni bir bos depo olustur (ornegin `cs-eklenti`).
2. Bu klasorun **icindekileri** (ust klasoru degil) depoya yukle. Telefonda en rahat yol Termux:
   ```
   pkg install git unzip
   unzip TavsiyeFilmizle_cs3_projesi.zip -d proje && cd proje
   git init && git add . && git commit -m "ilk"
   git branch -M main
   git remote add origin https://github.com/KULLANICI/DEPO.git
   git push -u origin main      # sifre yerine GitHub "personal access token" kullan
   ```
   Bilgisayarda: depoya "Add file -> Upload files" ile `.github` klasoru dahil her seyi surukle.
3. Depoda **Actions** sekmesine gir, "Build" calismasinin bitmesini bekle (3-6 dk).
4. Biten calismanin altinda **cs3-ciktilari** adli dosyayi indir; icinde `TavsiyeFilmizle.cs3` ve `plugins.json` var.

## Bilgisayarda kendin derlemek
JDK 17 + Android SDK + Gradle 8.10 gerekir (Android Studio hepsini getirir):
```
gradle make makePluginsJson
```
Cikti: `TavsiyeFilmizle/build/TavsiyeFilmizle.cs3`

## CloudStream'e kurma
- `repo.json` ve `plugins.json` icindeki `KULLANICI/DEPO` yerlerini kendi GitHub adin/deponla degistir.
- Actions ciktisindaki `plugins.json`'u deponun `builds` dalina koyarsan CloudStream'e depo adresiyle kurabilirsin.
- Dogrudan .cs3 dosyasi yukleme secenegi CloudStream surumune gore degisir, uygulamanin Eklentiler ekranindan kontrol et.

## Notlar
- Eklentinin Gradle/CloudStream surumleri resmi sablondan alindi. Derleme surum hatasi verirse
  https://github.com/recloudstream/plugins-template adresindeki guncel `build.gradle.kts` degerlerini kullan.
- Kart secicileri sabit degil (`/filmler10/` baglantisi + afis). Siteye ozel secici gerekirse `tools/` altindaki
  `cloudstream_pydroid_tam.py` araciyla yeni bir `.kt` uretip `TavsiyeFilmizle.kt` dosyasinin yerine koyabilirsin.
- Surum numarasini her yeni derlemede `TavsiyeFilmizle/build.gradle.kts` icinde artir.
