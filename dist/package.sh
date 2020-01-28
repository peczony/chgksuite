cp -rf ../chgksuite/resources .;
zip -r chgksuite_v${VERSION}_mac.zip resources chgksuite;
zip -r chgksuite_v${VERSION}_win.zip resources chgksuite.exe;
rm -rf resources;